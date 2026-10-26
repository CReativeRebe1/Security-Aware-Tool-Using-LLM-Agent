"""Build gate cases for one pool from logged tool-call proposals (+ their traces).

  python -m secgate.data.build_cases --pool test
  python -m secgate.data.build_cases --pool test --extra-proposals outputs/b0/proposals.jsonl \
         --extra-traces outputs/b0/traces.jsonl

Only state-changing calls are gated. Many pipelines propose the same call in the same scenario, so proposals are
deduplicated per scenario on (function, arguments). Every case passes the leakage guard before it is written.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ..config import load_config
from ..evidence.context import ContextBuilder
from ..evidence.tools import is_state_changing
from .cases import Case, save_cases
from .ground_truth import matches_task
from .io import content_key, read_jsonl
from .loaders import AgentDojoData, scenario_id
from .splits import Splits

_ABBR = {"workspace": "ws", "banking": "bank"}


def dedupe_key(row: dict) -> str:
    sid = scenario_id(row["suite"], row["user_task_id"], row["injection_task_id"])
    return content_key(sid, row["proposed_call"]["function"], row["proposed_call"].get("args") or {})


def case_id_for(row: dict) -> str:
    return f"{_ABBR.get(row['suite'], row['suite'])}|{row['user_task_id']}|" \
           f"{row['injection_task_id'] or 'benign'}|{dedupe_key(row)[:8]}"


def categorise(row: dict, provenance: dict) -> str:
    """By oracle provenance: a call that merely resembles the attacker's goal (e.g. the user herself named the same
    IBAN in an older task version) is not counted as injection-caused."""
    if not row["injection_task_id"]:
        return "benign"
    if provenance["origin"]["trust"] == "untrusted":
        return "injection_goal"
    if any(r["trust"] == "untrusted" for r in provenance["args"]):
        return "injection_argument"          # not flagged as the attacker's goal, but copies an injected value
    return "injection_scenario"


def select(data: AgentDojoData, splits: Splits, pool: str, attacks: set[str] | None,
           extra: list[Path]) -> list[dict]:
    def keep(r: dict) -> bool:
        if not r.get("user_task_id") or not is_state_changing(r["proposed_call"]["function"]):
            return False
        if attacks and r["attack_type"] not in attacks:
            return False
        sid = scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"])
        return sid in data.scenarios and splits.in_pool(sid, pool)

    rows = list(data.iter_proposals(keep))
    for p in extra:
        rows += [r for r in read_jsonl(p) if keep(r)]
    by_key: dict[str, dict] = {}
    for r in rows:      # first occurrence wins; later duplicates only add their pipeline name
        k = dedupe_key(r)
        if k in by_key:
            by_key[k]["_pipelines"].add(r["pipeline"])
        else:
            by_key[k] = dict(r, _pipelines={r["pipeline"]})
    return list(by_key.values())


def build(pool: str, cfg_path: str | None = None, attacks: set[str] | None = None, extra_proposals=(),
          extra_traces=(), out: str | None = None, limit: int | None = None) -> Path:
    cfg = load_config(cfg_path)
    data = AgentDojoData(cfg.data_dir)
    splits = Splits(data)
    builder = ContextBuilder(cfg, data)
    rows = select(data, splits, pool, attacks, [Path(p) for p in extra_proposals])
    if limit:
        rows = rows[:limit]
    traces = data.traces_by_id({r["trace_id"] for r in rows}, extra_files=extra_traces)
    cases, stats = [], Counter()
    for r in rows:
        tr = traces.get(r["trace_id"])
        if tr is None:
            stats["missing_trace"] += 1
            continue
        inj_task = data.injection_tasks.get((r["suite"], r["injection_task_id"])) if r["injection_task_id"] else None
        goal = matches_task(r["proposed_call"], inj_task)
        gi, extras = builder.from_proposal(r, tr, case_id_for(r), goal_match=goal)
        sid = scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"])
        case = Case(
            input=gi, pool=splits.base_pool(sid), subset="executable", scenario_id=sid,
            proposal_id=r["proposal_id"], category=categorise(r, gi.provenance),
            alt_provenance=extras["provenance"],
            meta={"trace_id": r["trace_id"], "pipelines": sorted(r["_pipelines"]), "attack_type": r["attack_type"],
                  "matches_user_task_ground_truth": matches_task(
                      r["proposed_call"], data.user_tasks.get((r["suite"], r["user_task_id"]))),
                  "matches_injection_task_ground_truth": goal,
                  "dataset_flags": {k: r.get(k) for k in ("matches_user_task_ground_truth",
                                                          "matches_injection_task_ground_truth")},
                  "trace_utility": r.get("trace_utility"), "trace_attack_succeeded": r.get("trace_attack_succeeded"),
                  "retrieved_ids": extras["retrieved_ids"]},
        )
        splits.assert_pool(case, pool)
        cases.append(case)
        stats[f"{r['suite']}/{case.category}"] += 1
    path = Path(out) if out else cfg.outputs_dir / "cases" / f"{pool}_candidates.jsonl"
    n = save_cases(path, cases)
    print(f"wrote {n} cases -> {path} (truncated tool outputs: {builder.truncated})")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True, choices=["train", "train_only", "dev", "test"])
    ap.add_argument("--config", default=None)
    ap.add_argument("--attacks", default=None, help="comma-separated attack types to keep (default: all)")
    ap.add_argument("--extra-proposals", nargs="*", default=[])
    ap.add_argument("--extra-traces", nargs="*", default=[])
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None, help="keep only the first N proposals (smoke runs)")
    a = ap.parse_args(argv)
    build(a.pool, a.config, set(a.attacks.split(",")) if a.attacks else None, a.extra_proposals, a.extra_traces,
          a.out, a.limit)


if __name__ == "__main__":
    main()
