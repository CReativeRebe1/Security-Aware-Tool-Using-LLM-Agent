"""Run one condition over a case file through the resolution loop -> predictions/<condition>[_noisy].jsonl.

  python -m secgate.eval.run_gate --condition b1_rules --cases outputs/cases/test_candidates.jsonl --pool test
  python -m secgate.eval.run_gate --condition b3_prompt_4way --cases ... --responses noisy --shard 0 --num-shards 2

Resumable: one line per case, keyed by condition, case, responses and the masked input. Cases without a fixed
user response (before annotation) are answered by the ScenarioResponder.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..config import Condition, load_condition, load_config
from ..data.cases import iter_cases
from ..data.io import KeyedStore, content_key
from ..data.loaders import AgentDojoData
from ..data.splits import Splits
from ..evidence.mask import EvidenceMask
from ..gate.rules import RulesGate
from ..manifest import write_manifest
from ..resolution.loop import resolve
from ..resolution.responders import FixedUserResponder, MockApprover, ScenarioResponder


def make_gate(cond: Condition, cfg, out_dir: Path, backend=None, model_id: str | None = None,
              threshold: float | None = None, cite: bool = False):
    """(gate, backend). Rules need no model; LLM gates reuse `backend` when given."""
    if cond.gate_kind == "rules":
        return RulesGate(cond.decision_space), backend
    from ..gate.llm_gate import LLMGate
    from ..models.backend import load_backend

    if backend is None:
        backend = load_backend(cfg, model_id=model_id)
    adapter = None
    if cond.adapter:
        path = Path(cond.adapter)
        path = path if path.is_absolute() else cfg.outputs_dir / path
        if not getattr(backend, "has_peft", False) or cond.name not in backend.model.peft_config:
            backend.load_adapter(cond.name, str(path))
        adapter = cond.name
    gate = LLMGate(backend, cond.decision_space, cond.intermediate, adapter=adapter,
                   cache_path=out_dir / "gate_cache" / f"{cond.name}.jsonl", cite=cite, allow_threshold=threshold,
                   name=cond.name)
    return gate, backend


def run(condition: str, cases_path: str, pool: str, cfg_path: str | None = None, responses: str = "clean",
        out: str | None = None, shard: int = 0, num_shards: int = 1, limit: int | None = None,
        model_id: str | None = None, threshold: float | None = None, cite: bool = False, backend=None) -> Path:
    cfg = load_config(cfg_path)
    cond = load_condition(condition)
    data = AgentDojoData(cfg.data_dir)
    splits = Splits(data)
    out_dir = Path(out) if out else cfg.outputs_dir / "predictions" / pool
    out_dir.mkdir(parents=True, exist_ok=True)

    gate, backend = make_gate(cond, cfg, out_dir, backend, model_id, threshold, cite)
    mask = EvidenceMask.for_condition(cond)
    noisy = responses == "noisy"
    rcfg = cfg["resolution"]
    user = FixedUserResponder(noisy, fallback=ScenarioResponder(data, rcfg["user_noise"], noisy, cfg["seed"]))
    approver = MockApprover(cfg.resources_dir)

    stem = cond.name + ("_noisy" if noisy else "") + (f"_t{threshold:.3f}" if threshold is not None else "")
    stem += f".shard{shard}" if num_shards > 1 else ""
    write_manifest(out_dir / f"{stem}.manifest.json", cfg, extra={
        "stage": "predictions", "condition": cond.name, "cases": str(cases_path), "pool": pool,
        "responses": responses, "model_id": getattr(backend, "model_id", None), "threshold": threshold})
    store = KeyedStore(out_dir / f"{stem}.jsonl")
    done, t0 = 0, time.time()
    for i, case in enumerate(iter_cases(cases_path)):
        if i % num_shards != shard:
            continue
        splits.assert_pool(case, pool)
        gi = mask.apply(case.input, case.alt_provenance)
        key = content_key(cond.name, case.case_id, responses, threshold, gi.to_dict())
        if key in store:
            continue
        tr = resolve(case, gi, gate, user, approver, cond.name, rcfg["max_rounds"], cond.resolution)
        store.put(key, {**tr.to_dict(), "subset": case.subset, "category": case.category, "pool": case.pool,
                        "responses": responses})
        done += 1
        if done % 25 == 0:
            print(f"[{stem}] {done} new ({(time.time() - t0) / done:.2f}s/case)", flush=True)
        if limit and done >= limit:
            break
    store.close()
    if hasattr(gate, "close"):
        gate.close()
    if getattr(backend, "long_inputs", 0):
        print(f"note: {backend.long_inputs} gate prompts exceeded model.max_input_tokens")
    print(f"{stem}: {len(store)} predictions -> {store.path}")
    return store.path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", required=True, help="name in configs/conditions, or a YAML path")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--pool", required=True, choices=["train", "dev", "test"], help="leakage guard pool")
    ap.add_argument("--config", default=None)
    ap.add_argument("--responses", default="clean", choices=["clean", "noisy"])
    ap.add_argument("--out", default=None, help="predictions dir (default: <outputs>/predictions/<pool>)")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--threshold", type=float, default=None, help="binary gates: ALLOW iff p_allow >= threshold")
    ap.add_argument("--cite", action="store_true", help="also generate evidence_cited (error analysis)")
    a = ap.parse_args(argv)
    run(a.condition, a.cases, a.pool, a.config, a.responses, a.out, a.shard, a.num_shards, a.limit, a.model_id,
        a.threshold, a.cite)


if __name__ == "__main__":
    main()
