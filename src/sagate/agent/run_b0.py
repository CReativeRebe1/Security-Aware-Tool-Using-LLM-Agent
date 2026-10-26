"""B0: run the Qwen3 agent (no gate) over the strict train/test scenarios and cache traces in the dataset's
trace schema (NB01). Resumable: finished trace_ids are skipped; traces that crashed (e.g. CUDA OOM) are retried.

  python -m sagate.agent.run_b0 --out outputs/b0_traces --shard 0 --num-shards 2
  python -m sagate.agent.run_b0 --merge outputs/b0_traces/traces_shard*.jsonl --out outputs/b0_traces
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from collections import defaultdict
from pathlib import Path

from ..config import load_config
from ..data.loaders import AgentDojoData, scenario_id, write_jsonl
from ..data.splits import Splits
from ..gate.cache import JsonlStore
from ..manifest import write_manifest

PIPELINE_ID = "qwen3-8b"


def trace_id(suite: str, user_task: str, attack: str, injection_task: str | None) -> str:
    return f"{PIPELINE_ID}|{suite}|{user_task}|{attack if injection_task else 'none'}|{injection_task or 'none'}"


def scenario_list(data: AgentDojoData, pools: list[str], suites: list[str] | None) -> list[dict]:
    splits = Splits(data)
    out = [s for sid, s in sorted(data.scenarios.items())
           if any(splits.in_pool(sid, p) for p in pools) and (not suites or s["suite"] in suites)]
    return out


def merge(shards: list[str], out_dir: Path, data: AgentDojoData) -> dict:
    """Shards -> traces.jsonl (one row per trace_id, latest attempt wins, partial lines skipped) + b0_summary.json:
    B0 utility and attack success rate per pool and suite, with raw counts."""
    rows: dict[str, dict] = {}
    for s in shards:
        with JsonlStore(s) as st:
            rows.update((r["key"], r) for r in st.values())
    write_jsonl(out_dir / "traces.jsonl", rows.values())
    splits = Splits(data)
    agg: dict = defaultdict(lambda: {"traces": 0, "errors": 0, "utility": 0, "attacked": 0, "attack_succeeded": 0})
    for r in rows.values():
        pool = splits.pool_of(scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"]))
        for key in ((pool, r["suite"]), (pool, "all")):
            a = agg[key]
            a["traces"] += 1
            a["errors"] += bool(r.get("error"))
            a["utility"] += bool(r.get("utility"))
            if r.get("injection_task_id"):
                a["attacked"] += 1
                a["attack_succeeded"] += bool(r.get("attack_succeeded"))
    summary = {f"{p}/{s}": {**a, "utility_rate": f"{a['utility']}/{a['traces']}",
                            "asr": f"{a['attack_succeeded']}/{a['attacked']}"} for (p, s), a in sorted(agg.items())}
    (out_dir / "b0_summary.json").write_text(json.dumps(summary, indent=1))
    for k, v in summary.items():
        print(f"  {k:22s} utility {v['utility_rate']:>9s}  ASR {v['asr']:>9s}  errors {v['errors']}")
    return summary


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None, help="output dir (default: <outputs>/b0_traces)")
    ap.add_argument("--pools", default="train,test")
    ap.add_argument("--suites", default=None)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="stop after N new traces (smoke tests)")
    ap.add_argument("--model-id", default=None, help="override model.base_id (e.g. a small model for smoke tests)")
    ap.add_argument("--merge", nargs="+", default=None, metavar="SHARD",
                    help="CPU only: merge shard files into <out>/traces.jsonl and write <out>/b0_summary.json")
    a = ap.parse_args(argv)

    if a.merge:
        cfg = load_config(a.config)
        out_dir = Path(a.out) if a.out else cfg.outputs_dir / "b0_traces"
        merge(a.merge, out_dir, AgentDojoData(cfg.data_dir))
        return

    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.task_suite.load_suites import get_suite

    from ..models.backend import backend_from_config
    from .pipeline import jsonify, make_b0_pipeline

    cfg = load_config(a.config)
    data = AgentDojoData(cfg.data_dir)
    out_dir = Path(a.out) if a.out else cfg.outputs_dir / "b0_traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    scen = scenario_list(data, a.pools.split(","), a.suites.split(",") if a.suites else None)
    scen = [s for i, s in enumerate(scen) if i % a.num_shards == a.shard]
    attack_name = cfg["agent"]["attack"]
    version = cfg["agent"]["benchmark_version"]

    backend = backend_from_config(cfg, model_id=a.model_id)
    pipeline, recorder, llm = make_b0_pipeline(backend, cfg)
    write_manifest(out_dir / f"manifest_shard{a.shard}.json", cfg,
                   extra={"stage": "b0_traces", "model_id": backend.model_id, "shard": a.shard,
                          "num_shards": a.num_shards, "scenarios": len(scen), "attack": attack_name,
                          "benchmark_version": version})
    store = JsonlStore(out_dir / f"traces_shard{a.shard}.jsonl")
    attacks: dict = {}
    done = 0
    for s in scen:
        tid = trace_id(s["suite"], s["user_task_id"], attack_name, s["injection_task_id"])
        if tid in store and not store.get(tid).get("error"):
            continue
        suite = get_suite(version, s["suite"])
        user_task = suite.get_user_task_by_id(s["user_task_id"])
        inj_task = suite.get_injection_task_by_id(s["injection_task_id"]) if s["injection_task_id"] else None
        injections = {}
        if inj_task is not None:
            if s["suite"] not in attacks:
                attacks[s["suite"]] = load_attack(attack_name, suite, pipeline)
            injections = attacks[s["suite"]].attack(user_task, inj_task)
        t0, err = time.time(), None
        utility, security = False, None
        recorder.messages = []
        try:
            utility, security = suite.run_task_with_pipeline(pipeline, user_task, inj_task, injections)
        except Exception as e:                      # keep going; the failure is recorded in the trace
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        messages = jsonify(recorder.messages)
        store.put(tid, {
            "trace_id": tid, "pipeline": PIPELINE_ID, "suite": s["suite"], "user_task_id": s["user_task_id"],
            "injection_task_id": s["injection_task_id"],
            "attack_type": attack_name if inj_task else "none",
            "injections": injections, "utility": bool(utility),
            "attack_succeeded": (bool(security) if inj_task else None),
            "tool_calls": [tc for m in messages if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])],
            "messages": messages, "error": err, "duration": time.time() - t0,
        })
        done += 1
        print(f"[{done}] {tid} utility={utility} attack={security if inj_task else '-'} "
              f"({time.time() - t0:.0f}s, parse_failures={llm.parse_failures})", flush=True)
        if a.limit and done >= a.limit:
            break
    store.close()
    print(f"shard {a.shard}: {len(store)} traces in {out_dir}")


if __name__ == "__main__":
    main()
