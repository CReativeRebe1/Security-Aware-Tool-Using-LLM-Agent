"""B0 traces: the Qwen3 task agent with no gate over the strict-split scenarios, cached in the dataset's trace
schema. Test-source scenarios run first (they are needed for the end-to-end B0 numbers), then train-source.
Resumable: finished trace ids are skipped.

  python -m secgate.agent.run_b0 --out outputs/b0 --pools test,train --shard 0 --num-shards 2
"""

from __future__ import annotations

import argparse
import time
import traceback
from pathlib import Path

from ..config import load_config
from ..data.io import KeyedStore
from ..data.loaders import AgentDojoData
from ..data.splits import Splits
from ..manifest import write_manifest

PIPELINE_ID = "qwen3-8b"


def trace_id(suite: str, user_task: str, attack: str, injection_task: str | None) -> str:
    return f"{PIPELINE_ID}|{suite}|{user_task}|{attack if injection_task else 'none'}|{injection_task or 'none'}"


def scenario_order(data: AgentDojoData, pools: list[str], suites: list[str] | None) -> list[dict]:
    splits = Splits(data)
    out, seen = [], set()
    for pool in pools:                      # pool order = run order
        for sid in splits.scenarios_in(pool):
            s = data.scenarios[sid]
            if sid not in seen and (not suites or s["suite"] in suites):
                seen.add(sid)
                out.append(s)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None, help="output dir (default: <outputs>/b0)")
    ap.add_argument("--pools", default="test,train")
    ap.add_argument("--suites", default=None)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="stop after N new traces (smoke runs)")
    ap.add_argument("--model-id", default=None)
    a = ap.parse_args(argv)

    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.task_suite.load_suites import get_suite

    from ..models.backend import load_backend
    from .pipeline import jsonify, make_pipeline

    cfg = load_config(a.config)
    data = AgentDojoData(cfg.data_dir)
    out_dir = Path(a.out) if a.out else cfg.outputs_dir / "b0"
    out_dir.mkdir(parents=True, exist_ok=True)
    scen = scenario_order(data, a.pools.split(","), a.suites.split(",") if a.suites else None)
    scen = [s for i, s in enumerate(scen) if i % a.num_shards == a.shard]
    attack_name, version = cfg["agent"]["attack"], cfg["agent"]["benchmark_version"]

    backend = load_backend(cfg, model_id=a.model_id)
    pipeline, recorder, agent = make_pipeline(backend, cfg)
    write_manifest(out_dir / f"manifest_shard{a.shard}.json", cfg, extra={
        "stage": "b0_traces", "model_id": backend.model_id, "shard": a.shard, "num_shards": a.num_shards,
        "scenarios": len(scen), "attack": attack_name, "benchmark_version": version})
    store = KeyedStore(out_dir / f"traces_shard{a.shard}.jsonl")
    suites, attacks, done = {}, {}, 0
    for s in scen:
        tid = trace_id(s["suite"], s["user_task_id"], attack_name, s["injection_task_id"])
        if tid in store:
            continue
        suite = suites.setdefault(s["suite"], get_suite(version, s["suite"]))
        user_task = suite.get_user_task_by_id(s["user_task_id"])
        inj_task = suite.get_injection_task_by_id(s["injection_task_id"]) if s["injection_task_id"] else None
        injections = {}
        if inj_task is not None:
            if s["suite"] not in attacks:
                attacks[s["suite"]] = load_attack(attack_name, suite, pipeline)
            injections = attacks[s["suite"]].attack(user_task, inj_task)
        recorder.messages = []
        t0, err, utility, security = time.time(), None, False, None
        try:
            utility, security = suite.run_task_with_pipeline(pipeline, user_task, inj_task, injections)
        except Exception as e:            # keep going; the failure is recorded in the trace
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        messages = jsonify(recorder.messages)
        store.put(tid, {
            "trace_id": tid, "pipeline": PIPELINE_ID, "suite": s["suite"], "user_task_id": s["user_task_id"],
            "injection_task_id": s["injection_task_id"], "attack_type": attack_name if inj_task else "none",
            "injections": injections, "utility": bool(utility),
            "attack_succeeded": bool(security) if inj_task else None,
            "tool_calls": [{"function": tc["function"], "args": tc["args"]} for m in messages
                           if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])],
            "messages": messages, "error": err, "duration": time.time() - t0,
        })
        done += 1
        print(f"[{done}/{len(scen)}] {tid} utility={utility} attack={security if inj_task else '-'} "
              f"({time.time() - t0:.0f}s, parse failures so far {agent.parse_failures})", flush=True)
        if a.limit and done >= a.limit:
            break
    store.close()
    print(f"shard {a.shard}: {len(store)} traces in {store.path}")


if __name__ == "__main__":
    main()
