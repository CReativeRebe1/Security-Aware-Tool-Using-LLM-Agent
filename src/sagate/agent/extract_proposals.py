"""Traces -> tool_call_proposals rows in the dataset schema (data/processed/agentdojo/README.md).

Reuses the dataset's rules: `arg_provenance` = substring tags (reproduces the shipped column exactly),
`matches_*_ground_truth` = data.ground_truth (~99% agreement). `injection_seen_before_call` is whitespace/quote
insensitive here, so it also catches injections that YAML line-wrapping split (the shipped flag misses those).

  python -m sagate.agent.extract_proposals --traces runs/b0/traces.jsonl --out runs/b0/proposals.jsonl
"""

from __future__ import annotations

import argparse
from typing import Iterator

from ..config import load_config
from ..data.ground_truth import matches_ground_truth
from ..data.loaders import AgentDojoData, message_text, read_jsonl, write_jsonl
from ..evidence.provenance import arg_provenance, contains_injection


def _fc(tc) -> dict:
    return {"function": tc["function"], "args": dict(tc.get("args") or {})}


def proposals_from_trace(trace: dict, data: AgentDojoData) -> Iterator[dict]:
    suite, ut, it = trace["suite"], trace["user_task_id"], trace.get("injection_task_id")
    user_task = data.user_tasks.get((suite, ut))
    inj_task = data.injection_tasks.get((suite, it)) if it else None
    injections = list((trace.get("injections") or {}).values())
    msgs = trace["messages"]
    user_prompt = next((message_text(m) for m in msgs if m["role"] == "user"), "")
    prior: list[dict] = []
    step = 0
    for idx, m in enumerate(msgs):
        if m["role"] != "assistant" or not m.get("tool_calls"):
            continue
        tool_texts = [message_text(x) for x in msgs[:idx] if x["role"] == "tool"]
        seen = any(contains_injection(t, injections) for t in tool_texts) if injections else False
        for tc in m["tool_calls"]:
            call = _fc(tc)
            yield {
                "proposal_id": f"{trace['trace_id']}|{step}",
                "trace_id": trace["trace_id"],
                "message_index": idx,
                "step": step,
                "pipeline": trace["pipeline"],
                "suite": suite,
                "user_task_id": ut,
                "injection_task_id": it,
                "attack_type": trace["attack_type"],
                "user_prompt": user_prompt,
                "proposed_call": call,
                "prior_calls": list(prior),
                "injection_seen_before_call": seen,
                "arg_provenance": arg_provenance(call["args"], user_prompt, injections, tool_texts),
                "matches_user_task_ground_truth": matches_ground_truth(call, user_task),
                "matches_injection_task_ground_truth": matches_ground_truth(call, inj_task),
                "trace_utility": trace.get("utility"),
                "trace_attack_succeeded": trace.get("attack_succeeded"),
            }
            prior.append(call)
            step += 1


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traces", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    data = AgentDojoData(load_config(a.config).data_dir)
    rows = (p for path in a.traces for t in read_jsonl(path) for p in proposals_from_trace(t, data))
    print(f"wrote {write_jsonl(a.out, rows)} proposals -> {a.out}")


if __name__ == "__main__":
    main()
