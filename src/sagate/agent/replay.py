"""Replay executable cases from old logs in the pinned AgentDojo environment (ARCHITECTURE.md §5.0).

The logged runs carry no benchmark version and some predate v1.2.2. For each executable case, the calls before
the proposed one (its `prior_calls`) are re-executed in the pinned suite's environment with the trace's
injections and the user task's init, and each tool output is compared with the logged one (`same_output`:
quoting, line wrapping, list order and timestamps ignored; an error must reproduce as an error). Cases whose
prior calls do not reproduce are dropped from the executable subset before annotation. Qwen B0 cases (NB01) ran in the pinned version and are kept as is.
CPU only; needs the `agentdojo` extra.

  python -m sagate.agent.replay --cases outputs/cases/test_candidates.jsonl \
         --out outputs/cases/test_candidates.replayed.jsonl [--report outputs/cases/replay_test.json]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from ..config import load_config
from ..data.cases import Case, load_cases, save_cases
from ..data.loaders import AgentDojoData, message_text
from .run_b0 import PIPELINE_ID

_WS = re.compile(r"\s+")
_QUOTES = re.compile(r"['\"]|<<|>>")
# send_email / create_file stamp outputs with the current time, so logged and replayed timestamps never agree
_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?")
_WHOLE_FLOAT = re.compile(r"\b(\d+)\.0\b")          # amounts became floats: "for 1 sent" vs "for 1.0 sent"


def _norm(s: str) -> str:
    """Content, not formatting: YAML quoting and the spotlighting defence's << >> delimiters dropped (older versions
    dumped dates unquoted), wall-clock timestamps masked, whole floats as integers, whitespace collapsed."""
    s = _WHOLE_FLOAT.sub(r"\1", _DATETIME.sub("<datetime>", _QUOTES.sub("", s or "")))
    return _WS.sub(" ", s).strip()


def same_output(replayed: str, logged: str) -> bool:
    """Equal up to formatting: YAML re-wraps long strings at a different column, and lists built from sets
    (e.g. event participants) come out in another order, so compare without whitespace, then as token multisets."""
    a, b = _norm(replayed), _norm(logged)
    return a.replace(" ", "") == b.replace(" ", "") or sorted(a.split()) == sorted(b.split())


def replay_case(case: Case, trace: dict, version: str) -> dict:
    """{reproduced, checked, first_mismatch?} for one case."""
    from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite

    suite = get_suite(version, trace["suite"])
    env = suite.load_and_inject_default_environment(trace.get("injections") or {})
    if trace.get("user_task_id"):
        env = suite.get_user_task_by_id(trace["user_task_id"]).init_environment(env)
    runtime = FunctionsRuntime(suite.tools)
    logged = [m for m in trace["messages"] if m.get("role") == "tool"]
    calls = case.input.prior_calls
    if len(logged) < len(calls):
        return {"reproduced": False, "checked": 0, "reason": "trace has fewer tool outputs than prior calls"}
    for i, (call, msg) in enumerate(zip(calls, logged)):
        tc = msg.get("tool_call") or {}
        if tc.get("function") != call["function"]:
            return {"reproduced": False, "checked": i, "reason": f"call {i}: order differs from the trace"}
        out, err = runtime.run_function(env, call["function"], dict(call.get("args") or {}))
        if bool(err) != bool(msg.get("error")):
            return {"reproduced": False, "checked": i, "reason": f"call {i} {call['function']}: error "
                    f"{'appeared' if err else 'disappeared'}", "replayed_error": err, "logged_error": msg.get("error")}
        if not err and not same_output(tool_result_to_str(out), message_text(msg)):
            return {"reproduced": False, "checked": i, "reason": f"call {i} {call['function']}: output differs"}
    return {"reproduced": True, "checked": len(calls)}


def replay(case_path: str, out: str, report: str | None = None, cfg_path: str | None = None) -> dict:
    cfg = load_config(cfg_path)
    version = cfg["agent"]["benchmark_version"]
    data = AgentDojoData(cfg.data_dir)
    cases = load_cases(case_path)
    need = [c for c in cases if c.subset == "executable" and not c.meta.get("trace_id", "").startswith(PIPELINE_ID + "|")]
    need_ids = {c.case_id for c in need}
    traces = data.traces_by_id({c.meta["trace_id"] for c in need if c.meta.get("trace_id")})
    results, kept = {}, []
    for c in cases:
        if c.case_id not in need_ids:
            kept.append(c)
            continue
        tr = traces.get(c.meta.get("trace_id"))
        try:
            r = {"reproduced": False, "checked": 0, "reason": "trace not found"} if tr is None else \
                replay_case(c, tr, version)
        except Exception as e:          # e.g. injection vectors that the pinned version does not have
            r = {"reproduced": False, "checked": 0, "reason": f"replay failed: {type(e).__name__}"}
        results[c.case_id] = r
        c.meta["replay"] = {"version": version, **r}
        if r["reproduced"]:
            kept.append(c)
    save_cases(out, kept)
    summary = {"cases": len(cases), "replayed": len(need), "reproduced": sum(r["reproduced"] for r in results.values()),
               "kept": len(kept), "reasons": dict(Counter(r.get("reason", "").split(":")[-1].strip() or "ok"
                                                          for r in results.values()))}
    print(json.dumps(summary, indent=1))
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps({"summary": summary, "cases": results}, indent=1))
    return summary


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    replay(a.cases, a.out, a.report, a.config)


if __name__ == "__main__":
    main()
