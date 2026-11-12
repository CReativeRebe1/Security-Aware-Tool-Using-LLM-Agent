"""Case builder: tool-call proposals (+ their traces) -> GateInput cases for one pool.

  python -m sagate.data.build_cases --pool test [--extra-proposals runs/b0/proposals.jsonl --extra-traces ...]

Only state-changing calls are gated. Proposals are deduplicated per scenario (many pipelines propose the same
call). Every case passes splits.assert_pool() before it is written (P5).
"""

from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path

from ..config import load_config
from ..evidence.context_builder import ContextBuilder
from ..evidence.tools_registry import is_state_changing
from ..gate.cache import content_key
from .cases import Case, save_cases
from .loaders import AgentDojoData, read_jsonl, scenario_id
from .splits import Splits

_SUITE_ABBR = {"workspace": "ws", "banking": "bank"}


def dedupe_key(row: dict) -> str:
    sid = scenario_id(row["suite"], row["user_task_id"], row["injection_task_id"])
    prior = [c["function"] for c in row.get("prior_calls", [])]
    return content_key(sid, row["proposed_call"]["function"], row["proposed_call"].get("args"), prior)


def make_case_id(row: dict) -> str:
    inj = row["injection_task_id"] or "benign"
    return f"{_SUITE_ABBR.get(row['suite'], row['suite'])}|{row['user_task_id']}|{inj}|{dedupe_key(row)[:8]}"


def category(row: dict, provenance: list) -> str:
    if not row["injection_task_id"]:
        return "benign"
    call = next((r for r in provenance if r.get("kind") == "call"), {})
    return "injection" if call.get("trust") == "untrusted" else "injection_scenario_user_call"


def select_proposals(data: AgentDojoData, splits: Splits, pool: str, attacks: set[str] | None,
                     extra: list[Path], max_per_scenario: int | None, seed: int) -> list[dict]:
    def keep(r: dict) -> bool:
        if not is_state_changing(r["proposed_call"]["function"]):
            return False
        if r["user_task_id"] is None:
            return False
        if attacks and r["attack_type"] not in attacks:
            return False
        sid = scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"])
        return sid in data.scenarios and splits.in_pool(sid, pool)

    rows = list(data.iter_proposals(keep))
    for path in extra:
        rows += [r for r in read_jsonl(path) if keep(r)]
    # Qwen B0 proposals (if given via `extra`) come last, so dataset rows win duplicate keys; order is stable.
    seen, uniq = {}, []
    for r in rows:
        k = dedupe_key(r)
        if k in seen:
            seen[k]["meta_pipelines"].add(r["pipeline"])
            continue
        r = dict(r, meta_pipelines={r["pipeline"]})
        seen[k] = r
        uniq.append(r)
    if max_per_scenario:
        rng = random.Random(seed)
        by_s = defaultdict(list)
        for r in uniq:
            by_s[scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"])].append(r)
        uniq = [r for rs in by_s.values() for r in (rng.sample(rs, max_per_scenario) if len(rs) > max_per_scenario else rs)]
    return uniq


def build(pool: str, cfg_path: str | None = None, attacks: set[str] | None = None, extra_proposals=(),
          extra_traces=(), max_per_scenario: int | None = None, out: str | None = None) -> Path:
    cfg = load_config(cfg_path)
    data = AgentDojoData(cfg.data_dir)
    splits = Splits(data)
    builder = ContextBuilder(cfg, data)
    rows = select_proposals(data, splits, pool, attacks, [Path(p) for p in extra_proposals], max_per_scenario,
                            cfg["seed"])
    traces = data.traces_by_id({r["trace_id"] for r in rows}, extra_files=extra_traces)
    cases, stats = [], Counter()
    for r in rows:
        tr = traces.get(r["trace_id"])
        if tr is None:
            stats["missing_trace"] += 1
            continue
        gi, extras = builder.from_proposal(r, tr, case_id=make_case_id(r))
        sid = scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"])
        c = Case(
            input=gi, pool=splits.pool_of(sid), subset="executable", scenario_id=sid, proposal_id=r["proposal_id"],
            category=category(r, gi.provenance), alt_provenance=extras["provenance"],
            meta={
                "trace_id": r["trace_id"], "pipelines": sorted(r["meta_pipelines"]), "attack_type": r["attack_type"],
                "matches_user_task_ground_truth": r.get("matches_user_task_ground_truth"),
                "matches_injection_task_ground_truth": r.get("matches_injection_task_ground_truth"),
                "trace_utility": r.get("trace_utility"), "trace_attack_succeeded": r.get("trace_attack_succeeded"),
                "retrieved_ids": extras["retrieved_ids"],
            },
        )
        splits.assert_pool(c, "train" if pool in ("train", "dev") else pool)
        cases.append(c)
        stats[(r["suite"], c.category)] += 1
    path = Path(out) if out else cfg.outputs_dir / "cases" / f"{pool}_candidates.jsonl"
    n = save_cases(path, cases)
    print(f"wrote {n} cases -> {path}  (truncated untrusted blocks: {builder.truncations})")
    for k, v in sorted(stats.items(), key=str):
        print(f"  {k}: {v}")
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True, choices=["train", "dev", "test"])
    ap.add_argument("--config", default=None)
    ap.add_argument("--attacks", default=None, help="comma-separated attack types to keep (default: all)")
    ap.add_argument("--extra-proposals", nargs="*", default=[])
    ap.add_argument("--extra-traces", nargs="*", default=[])
    ap.add_argument("--max-per-scenario", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    build(a.pool, a.config, set(a.attacks.split(",")) if a.attacks else None, a.extra_proposals, a.extra_traces,
          a.max_per_scenario, a.out)


if __name__ == "__main__":
    main()
