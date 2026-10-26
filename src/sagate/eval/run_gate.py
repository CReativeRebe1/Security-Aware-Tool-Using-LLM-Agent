"""Run one condition over a case file with the resolution loop -> predictions/<condition>[_noisy].jsonl (NB02/NB04).

  python -m sagate.eval.run_gate --condition b1_rules --cases outputs/cases/test.jsonl
  python -m sagate.eval.run_gate --condition b3_prompt_4way --cases ... --responses noisy --shard 0 --num-shards 2

Resumable (one line per case, keyed by condition + case + responses + masked input). Cases without a fixed
`user_response` (before annotation) fall back to the ScenarioResponder.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..config import Condition, load_condition, load_config
from ..data.cases import iter_cases
from ..data.loaders import AgentDojoData
from ..data.splits import Splits
from ..evidence.mask import EvidenceMask
from ..gate.cache import GateCache, JsonlStore, content_key
from ..gate.rules import RulesGate
from ..manifest import write_manifest
from ..resolution.loop import resolve
from ..resolution.responders import FixedUserResponder, MockApprover, ScenarioResponder


def make_gate(cond: Condition, cfg, out_dir: Path, model_id: str | None = None, adapter_dir: str | None = None,
              threshold: float | None = None, cite: bool = False, backend=None):
    if cond.gate_kind == "rules":
        return RulesGate(cond.decision_space), None
    from ..gate.llm_gate import LLMGate
    from ..models.backend import backend_from_config

    adapters = {}
    if cond.adapter:
        path = Path(adapter_dir) / Path(cond.adapter).name if adapter_dir else Path(cond.adapter)
        if not path.is_absolute() and not path.exists():
            path = cfg.outputs_dir / cond.adapter
        adapters[cond.name] = str(path)
    if backend is None:
        backend = backend_from_config(cfg, adapters=adapters, model_id=model_id)
    else:
        for name, path in adapters.items():
            backend.load_adapter(name, path)
    gate = LLMGate(backend, cond.decision_space, cond.intermediate, adapter=cond.name if cond.adapter else None,
                   cache=GateCache(out_dir / "gate_cache" / f"{cond.name}.jsonl"), cite=cite,
                   allow_threshold=threshold)
    return gate, backend


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", required=True, help="name in configs/conditions or a YAML path")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--pool", default="test", choices=["train", "dev", "test"],
                    help="every case is checked against this pool (leakage guard)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--responses", default="clean", choices=["clean", "noisy"])
    ap.add_argument("--out", default=None, help="predictions dir (default: <outputs>/predictions)")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--adapter-dir", default=None)
    ap.add_argument("--threshold", type=float, default=None, help="binary gates: ALLOW iff p_allow >= threshold")
    ap.add_argument("--cite", action="store_true", help="also generate evidence_cited (B5 error analysis)")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    cond = load_condition(a.condition)
    data = AgentDojoData(cfg.data_dir)
    splits = Splits(data)
    out_dir = Path(a.out) if a.out else cfg.outputs_dir / "predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.pool == "test" and a.threshold is not None and cond.extra.get("threshold", {}).get("pool") == "dev":
        print("note: threshold must be selected on dev (eval.pareto); applying a fixed threshold to test")

    gate, backend = make_gate(cond, cfg, out_dir, a.model_id, a.adapter_dir, a.threshold, a.cite)
    mask = EvidenceMask.from_condition(cond)
    noisy = a.responses == "noisy"
    res_cfg = cfg["resolution"]
    user = FixedUserResponder(noisy=noisy, fallback=ScenarioResponder(data, res_cfg["user_noise"], noisy, cfg["seed"]))
    approver = MockApprover(cfg.resources_dir)

    suffix = "" if not noisy else "_noisy"
    if a.threshold is not None:
        suffix += f"_t{a.threshold:.3f}"
    shard = f".shard{a.shard}" if a.num_shards > 1 else ""
    pred_path = out_dir / f"{cond.name}{suffix}{shard}.jsonl"
    write_manifest(out_dir / f"{cond.name}{suffix}{shard}.manifest.json", cfg,
                   extra={"stage": "predictions", "condition": cond.__dict__, "cases": a.cases,
                          "responses": a.responses, "model_id": getattr(backend, "model_id", None)})
    store = JsonlStore(pred_path)
    n_new, t0 = 0, time.time()
    for i, case in enumerate(iter_cases(a.cases)):
        if i % a.num_shards != a.shard:
            continue
        splits.assert_pool(case, "train" if a.pool in ("train", "dev") else a.pool)
        gi = mask.apply(case.input, case.alt_provenance)
        key = content_key(cond.name, case.case_id, a.responses, a.threshold, gi.to_dict())
        if key in store:
            continue
        tr = resolve(case, gi, gate, user, approver, cond.name, res_cfg["max_rounds"], cond.resolution)
        store.put(key, {**tr.to_dict(), "subset": case.subset, "category": case.category, "pool": case.pool,
                        "responses": a.responses})
        n_new += 1
        if n_new % 25 == 0:
            print(f"[{cond.name}] {n_new} cases ({(time.time() - t0) / n_new:.2f}s/case)", flush=True)
        if a.limit and n_new >= a.limit:
            break
    store.close()
    if backend is not None and getattr(backend, "long_inputs", 0):
        print(f"warning: {backend.long_inputs} gate prompts exceeded model.max_input_tokens")
    print(f"{cond.name}: {len(store)} predictions -> {pred_path}")


if __name__ == "__main__":
    main()
