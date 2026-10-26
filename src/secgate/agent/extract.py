"""Traces -> one row per proposed tool call, in the schema of data/processed/agentdojo/tool_call_proposals.jsonl.gz,
so B0 proposals plug straight into the case builder.

  python -m secgate.agent.extract --traces outputs/b0/traces_shard*.jsonl --out-traces outputs/b0/traces.jsonl \
         --out outputs/b0/proposals.jsonl
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

from ..config import load_config
from ..data.ground_truth import matches_task
from ..data.io import read_jsonl, write_jsonl
from ..data.loaders import AgentDojoData, message_text
from ..evidence.provenance import contains_injection, dataset_tags


def _calls(msg: dict) -> list[dict]:
    out = []
    for tc in msg.get("tool_calls") or []:
        out.append({"function": tc.get("function"), "args": tc.get("args") or {}})
    return out


def proposals_from_trace(trace: dict, user_prompt: str, user_task: dict | None,
                         injection_task: dict | None) -> list[dict]:
    rows, prior, step = [], [], 0
    injections = list((trace.get("injections") or {}).values())
    msgs = trace.get("messages") or []
    for idx, m in enumerate(msgs):
        if m.get("role") != "assistant":
            continue
        tool_texts = [message_text(x) for x in msgs[:idx] if x.get("role") == "tool"]
        seen = any(contains_injection(t, injections) for t in tool_texts) if injections else False
        for call in _calls(m):
            rows.append({
                "proposal_id": f"{trace['trace_id']}|{step}", "trace_id": trace["trace_id"], "message_index": idx,
                "step": step, "pipeline": trace["pipeline"], "suite": trace["suite"],
                "user_task_id": trace["user_task_id"], "injection_task_id": trace["injection_task_id"],
                "attack_type": trace["attack_type"], "user_prompt": user_prompt, "proposed_call": call,
                "prior_calls": list(prior), "injection_seen_before_call": seen,
                "arg_provenance": {k: dataset_tags(v, user_prompt, injections, tool_texts)
                                   for k, v in call["args"].items()},
                "matches_user_task_ground_truth": matches_task(call, user_task),
                "matches_injection_task_ground_truth": matches_task(call, injection_task),
                "trace_utility": trace.get("utility"), "trace_attack_succeeded": trace.get("attack_succeeded"),
            })
            prior.append(call)
            step += 1
    return rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traces", nargs="+", required=True, help="trace files (KeyedStore or plain JSONL; globs ok)")
    ap.add_argument("--out", required=True, help="proposals JSONL")
    ap.add_argument("--out-traces", default=None, help="also write the merged traces as plain JSONL")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    data = AgentDojoData(cfg.data_dir)
    paths = sorted({p for pat in a.traces for p in (glob.glob(pat) or [pat])})
    traces = []
    for p in paths:
        for r in read_jsonl(p):
            traces.append(r["value"] if "key" in r and "value" in r else r)
    rows = []
    for t in traces:
        ut = data.user_tasks.get((t["suite"], t["user_task_id"]))
        it = data.injection_tasks.get((t["suite"], t["injection_task_id"])) if t["injection_task_id"] else None
        first_user = next((message_text(m) for m in t.get("messages") or [] if m.get("role") == "user"), None)
        rows += proposals_from_trace(t, first_user or (ut or {}).get("prompt", ""), ut, it)
    if a.out_traces:
        write_jsonl(a.out_traces, traces)
    n = write_jsonl(Path(a.out), rows)
    print(f"{len(traces)} traces -> {n} proposals -> {a.out}")


if __name__ == "__main__":
    main()
