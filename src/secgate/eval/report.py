"""Summarise prediction files against a case file.

  python -m secgate.eval.report --cases outputs/cases/test_candidates.jsonl --pred outputs/predictions/test/*.jsonl \
         --json outputs/predictions/test/report.json

With annotated cases it prints the gold metrics; otherwise the pre-annotation dry-run report.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

from ..data.cases import load_cases
from ..data.io import read_jsonl
from .metrics import Rate, dry_run, gold_metrics, to_jsonable

_HEADLINE = ("final_resolution_success", "unauthorized_action_rate", "unnecessary_deferral_rate",
             "raw_deferral_rate", "mean_interactions", "first_round_accuracy", "binary_success",
             "macro_f1_missing_evidence", "macro_f1_required_authority")


def load_predictions(path: str | Path) -> list[dict]:
    rows = list(read_jsonl(path))
    return [r["value"] if "value" in r and "key" in r else r for r in rows]


def _fmt(v) -> str:
    if isinstance(v, Rate):
        return str(v)
    if isinstance(v, float):
        return f"{v:.3f}"
    return "-" if v is None else str(v)


def summarise(cases_path: str, pred_paths: list[str]) -> dict:
    cases = load_cases(cases_path)
    annotated = any(c.has_gold for c in cases)
    out = {"cases": cases_path, "annotated": annotated, "conditions": {}}
    for p in pred_paths:
        if p.endswith(".manifest.json") or Path(p).name == "report.json":
            continue
        preds = load_predictions(p)
        name = Path(p).stem
        m = gold_metrics(preds, cases) if annotated else dry_run(preds, cases)
        out["conditions"][name] = m
        print(f"\n== {name} ({'gold' if annotated else 'dry run, no gold labels'})")
        if annotated:
            for k in _HEADLINE:
                print(f"  {k:32s} {_fmt(m.get(k))}")
        else:
            print(f"  n={m['n']}  first={m['first']}  final={m['final']}  "
                  f"mean_interactions={_fmt(m['mean_interactions'])}")
            for cat, mix in m["first_by_category"].items():
                print(f"    {cat:34s} {mix}")
            print(f"  [heuristic] attack-goal calls not executed: {m['heuristic_attack_goal_not_executed']}")
            print(f"  [heuristic] user-task calls executed:       {m['heuristic_user_task_executed']}")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--pred", nargs="+", required=True, help="prediction files (globs allowed)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    paths = sorted({p for pat in a.pred for p in (glob.glob(pat) or [pat]) if p.endswith(".jsonl")})
    out = summarise(a.cases, paths)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(to_jsonable(out), indent=1), encoding="utf-8")
        print(f"\nreport -> {a.json}")


if __name__ == "__main__":
    main()
