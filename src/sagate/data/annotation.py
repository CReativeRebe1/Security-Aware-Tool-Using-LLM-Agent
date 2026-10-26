"""Annotation tooling (proposal §5): export cases for labelling, measure agreement, build the gold file.

  python -m sagate.data.annotation export --cases outputs/cases/test_candidates.jsonl --sample 160 \
         --out annotations/batch1.csv
  python -m sagate.data.annotation agreement annotations/batch1_*.csv
  python -m sagate.data.annotation gold annotations/batch1_adjudicated.csv --out annotations/gold.jsonl

Each annotator copies the exported CSV to <batch>_<annotator>.csv and fills the label columns. The annotator
sees the full-evidence rendering (no model output). The case author must not annotate their own cases.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from ..gate.prompts import render_input
from ..gate.schema import FIELD_VALUES
from ..eval.stats import krippendorff_alpha_nominal, pairwise_kappa
from .cases import load_cases
from .loaders import write_jsonl

LABEL_COLUMNS = ["gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority",
                 "gold_clause_ids", "user_response_text", "user_response_confirmed", "notes"]
AGREEMENT_FIELDS = ["gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority"]
_ALLOWED = {
    "gold_decision": set(FIELD_VALUES["decision"]),
    "gold_final_action": {"ALLOW", "BLOCK"},
    "gold_missing_evidence": set(FIELD_VALUES["missing_evidence"]),
    "gold_required_authority": set(FIELD_VALUES["required_authority"]),
}


def export(cases_path: str, out: str, sample: int | None, seed: int, stratify: bool = True) -> None:
    cases = load_cases(cases_path)
    rng = random.Random(seed)
    if sample and sample < len(cases):
        if stratify:   # spread over suite x category so rare kinds are not drowned out
            groups = defaultdict(list)
            for c in cases:
                groups[(c.input.suite, c.category)].append(c)
            for g in groups.values():
                rng.shuffle(g)
            picked, keys = [], sorted(groups)
            while len(picked) < sample and any(groups.values()):
                for k in keys:
                    if groups[k] and len(picked) < sample:
                        picked.append(groups[k].pop())
            cases = picked
        else:
            cases = rng.sample(cases, sample)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "suite", "category", "subset", "case_text", *LABEL_COLUMNS])
        for c in cases:
            w.writerow([c.case_id, c.input.suite, c.category, c.subset, render_input(c.input), *[""] * len(LABEL_COLUMNS)])
    print(f"exported {len(cases)} cases -> {out}")


def _read(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate(rows: list[dict], path: str) -> list[str]:
    errs = []
    for r in rows:
        for col, allowed in _ALLOWED.items():
            v = (r.get(col) or "").strip()
            if v and v not in allowed:
                errs.append(f"{path}: {r['case_id']}: {col}={v!r} not in {sorted(allowed)}")
        if r.get("gold_decision") in ("ALLOW", "BLOCK") and r.get("gold_final_action") and \
                r["gold_final_action"] != r["gold_decision"]:
            errs.append(f"{path}: {r['case_id']}: final action must equal an ALLOW/BLOCK first decision")
    return errs


def agreement(paths: list[str]) -> dict:
    """Krippendorff's α (nominal) per field across all annotators, plus pairwise Cohen's κ."""
    per_ann: dict[str, list[dict]] = {}
    errs = []
    for p in paths:
        name = Path(p).stem.rsplit("_", 1)[-1]
        per_ann[name] = rows = _read(p)
        errs += validate(rows, p)
    for e in errs:
        print("invalid:", e, file=sys.stderr)
    out = {}
    for f in AGREEMENT_FIELDS:
        labels = {a: {r["case_id"]: r[f].strip() for r in rows if r.get(f, "").strip()} for a, rows in per_ann.items()}
        cases = sorted({k for d in labels.values() for k in d})
        units = [[labels[a][k] for a in labels if k in labels[a]] for k in cases]
        out[f] = {"alpha": krippendorff_alpha_nominal(units),
                  "n_units": sum(len(u) >= 2 for u in units),
                  "kappa": {f"{a}-{b}": v for (a, b), v in pairwise_kappa(labels).items()}}
    return out


def gold(adjudicated: str, out: str) -> None:
    rows = _read(adjudicated)
    errs = validate(rows, adjudicated)
    if errs:
        raise SystemExit("\n".join(errs))
    gold_rows = []
    for r in rows:
        if not r.get("gold_decision"):
            continue
        g = {k: r[k].strip() for k in AGREEMENT_FIELDS if r.get(k)}
        if g["gold_decision"] in ("ALLOW", "BLOCK"):
            g.setdefault("gold_final_action", g["gold_decision"])
        g["case_id"] = r["case_id"]
        g["gold_clause_ids"] = [x.strip() for x in (r.get("gold_clause_ids") or "").replace(";", ",").split(",") if x.strip()]
        if r.get("user_response_text"):
            conf = (r.get("user_response_confirmed") or "").strip().lower()
            g["user_response"] = {"text": r["user_response_text"], "provides": g.get("gold_missing_evidence"),
                                  "confirmed": {"yes": True, "true": True, "no": False, "false": False}.get(conf)}
        gold_rows.append(g)
    print(f"wrote {write_jsonl(out, gold_rows)} gold rows -> {out}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--cases", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--sample", type=int, default=None)
    e.add_argument("--seed", type=int, default=42)
    g = sub.add_parser("agreement")
    g.add_argument("csvs", nargs="+")
    d = sub.add_parser("gold")
    d.add_argument("adjudicated")
    d.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "export":
        export(a.cases, a.out, a.sample, a.seed)
    elif a.cmd == "agreement":
        print(json.dumps(agreement(a.csvs), indent=1))
    else:
        gold(a.adjudicated, a.out)


if __name__ == "__main__":
    main()
