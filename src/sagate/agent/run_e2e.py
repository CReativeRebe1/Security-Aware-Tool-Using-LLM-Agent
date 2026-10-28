"""End-to-end gated runs (NB05, proposal §7: B0 vs B5 mandatory, B3 if time): the Qwen3 agent with
GatedToolsExecutor over the strict test scenarios, scored by AgentDojo (utility, attack success).

B0 is NB01 (run_b0, same agent, same scenarios). Live runs differ from the offline protocol: provenance is
inferred from the live conversation (the gate cannot know which text is injected), the user is the
ScenarioResponder (confirms calls matching the user task's ground truth, 15% seeded noise with
`--responses noisy`) and the approver is the MockApprover. Resumable, sharded like run_b0.

  python -m sagate.agent.run_e2e --condition b5_qlora_4way --adapter-dir outputs/adapters --shard 0 --num-shards 2
  python -m sagate.agent.run_e2e --condition b5_qlora_4way --merge outputs/e2e/b5_qlora_4way/traces_shard*.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_condition, load_config
from ..data.loaders import AgentDojoData
from ..gate.cache import JsonlStore
from ..manifest import write_manifest
from .run_b0 import PIPELINE_ID, merge, run_scenarios, scenario_list


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", required=True, help="gate condition (b5_qlora_4way, b3_prompt_4way, b1_rules)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None, help="default: <outputs>/e2e/<condition>")
    ap.add_argument("--pools", default="test")
    ap.add_argument("--suites", default=None)
    ap.add_argument("--responses", default="noisy", choices=["clean", "noisy"],
                    help="live user replies; noisy = the proposal's 15%% wrong/unhelpful share (default)")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--adapter-dir", default=None)
    ap.add_argument("--merge", nargs="+", default=None, metavar="SHARD")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    cond = load_condition(a.condition)
    data = AgentDojoData(cfg.data_dir)
    out_dir = Path(a.out) if a.out else cfg.outputs_dir / "e2e" / cond.name
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.merge:
        merge(a.merge, out_dir, data)
        return

    from ..eval.run_gate import make_gate
    from ..evidence.context_builder import ContextBuilder
    from ..evidence.mask import EvidenceMask
    from ..models.backend import backend_from_config
    from ..resolution.responders import MockApprover, ScenarioResponder
    from .pipeline import GatedToolsExecutor, make_b0_pipeline

    scen = scenario_list(data, a.pools.split(","), a.suites.split(",") if a.suites else None)
    scen = [s for i, s in enumerate(scen) if i % a.num_shards == a.shard]
    backend = backend_from_config(cfg, model_id=a.model_id)
    gate, _ = make_gate(cond, cfg, out_dir, a.model_id, a.adapter_dir, backend=backend)
    res = cfg["resolution"]
    # live: only inferred provenance exists (oracle conditions run on it too); -provenance still drops it
    mask = EvidenceMask("none" if cond.provenance == "none" else "inferred", cond.authority, cond.sensitivity,
                        cond.rag)
    executor = GatedToolsExecutor(
        gate, ContextBuilder(cfg, data),
        ScenarioResponder(data, res["user_noise"], a.responses == "noisy", cfg["seed"]),
        MockApprover(cfg.resources_dir), cond.name, mask, res["max_rounds"], cond.resolution,
        cfg["context"].get("gate_read_only", False))
    pipeline, recorder, llm = make_b0_pipeline(backend, cfg, executor=executor)
    attack, version = cfg["agent"]["attack"], cfg["agent"]["benchmark_version"]
    write_manifest(out_dir / f"manifest_shard{a.shard}.json", cfg,
                   extra={"stage": "e2e", "condition": cond.__dict__, "model_id": backend.model_id,
                          "shard": a.shard, "num_shards": a.num_shards, "scenarios": len(scen), "attack": attack,
                          "responses": a.responses, "benchmark_version": version})
    store = JsonlStore(out_dir / f"traces_shard{a.shard}.jsonl")
    run_scenarios(scen, pipeline, recorder, llm, store, attack, version, pipeline_id=f"{PIPELINE_ID}+{cond.name}",
                  executor=executor, limit=a.limit)
    store.close()
    print(f"shard {a.shard}: {len(store)} gated traces in {out_dir}")


if __name__ == "__main__":
    main()
