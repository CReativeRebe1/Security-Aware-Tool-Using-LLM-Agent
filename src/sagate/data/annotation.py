"""Annotation tooling (proposal §5): export cases for labelling, measure agreement, build the gold file.

  python -m sagate.data.annotation export --cases outputs/cases/test_candidates.jsonl --sample 160 \
         --out annotations/batch1.csv
  python -m sagate.data.annotation agreement annotations/batch1_*.csv
  python -m sagate.data.annotation gold annotations/batch1_adjudicated.csv --out annotations/gold.jsonl
  python -m sagate.data.annotation freeze --cases outputs/cases/test_candidates.jsonl annotations/test_nl.jsonl \
         --gold annotations/gold.jsonl --pool test --out annotations/test_cases.jsonl

Each annotator copies the exported CSV to <batch>_<annotator>.csv and fills the label columns. The annotator
sees the full-evidence rendering (no model output). The case author must not annotate their own cases.
`freeze` writes the gold-labelled case file NB02/NB04 evaluate (annotations/<pool>_cases.jsonl).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ..gate.prompts import render_input
from ..gate.schema import DEFERRALS, FIELD_VALUES
from ..eval.stats import krippendorff_alpha_nominal, pairwise_kappa
from .cases import attach_gold, load_cases, save_cases
from .loaders import read_jsonl, write_jsonl

LABEL_COLUMNS = ["gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority",
                 "gold_clause_ids", "user_response_text", "user_response_confirmed",
                 "user_response_noisy_text", "user_response_noisy_confirmed", "notes"]
NOISE_RATE = 0.15        # proposal §7: 15% of fixed user replies are wrong or unhelpful
UNHELPFUL_REPLY = "I'm not sure, just do whatever makes sense."
_YES_NO = {"yes": True, "true": True, "no": False, "false": False}
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
        if (r.get("gold_decision") or "").strip() in DEFERRALS and not (r.get("gold_final_action") or "").strip():
            errs.append(f"{path}: {r['case_id']}: ASK_USER/ESCALATE needs gold_final_action (else it is never scored)")
    return errs


def _noisy(case_id: str, seed: int, rate: float) -> bool:
    """Seeded, per-case choice of which fixed replies are noisy."""
    h = hashlib.sha1(f"{seed}|{case_id}|noise".encode()).hexdigest()
    return int(h[:12], 16) / float(1 << 48) < rate


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


def gold(adjudicated: str, out: str, seed: int = 42, noise: float = NOISE_RATE) -> None:
    """Adjudicated CSV -> gold JSONL. A seeded `noise` share of the fixed user replies is marked noisy; the noisy
    run uses the annotators' noisy reply when given, else an unhelpful one."""
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
        if (r.get("category") or "").strip():
            g["category"] = r["category"].strip()
        g["gold_clause_ids"] = [x.strip() for x in (r.get("gold_clause_ids") or "").replace(";", ",").split(",") if x.strip()]
        if r.get("user_response_text"):
            conf = (r.get("user_response_confirmed") or "").strip().lower()
            resp = {"text": r["user_response_text"], "provides": g.get("gold_missing_evidence"),
                    "confirmed": _YES_NO.get(conf), "noisy": _noisy(r["case_id"], seed, noise)}
            if resp["noisy"]:
                noisy_text = (r.get("user_response_noisy_text") or "").strip()
                resp["noisy_text"] = noisy_text or UNHELPFUL_REPLY
                resp["noisy_confirmed"] = _YES_NO.get((r.get("user_response_noisy_confirmed") or "").strip().lower())
                resp["noisy_provides"] = "none"
            g["user_response"] = resp
        gold_rows.append(g)
    n_resp = sum("user_response" in g for g in gold_rows)
    n_noisy = sum(g.get("user_response", {}).get("noisy", False) for g in gold_rows)
    print(f"wrote {write_jsonl(out, gold_rows)} gold rows -> {out}  ({n_noisy}/{n_resp} user replies noisy)")


def freeze(case_paths: list[str], gold_path: str, pool: str, out: str, cfg_path: str | None = None) -> None:
    """Candidate cases (+ decision-only NL cases) + gold -> the frozen, gold-labelled case file for one pool."""
    from ..config import load_config
    from .loaders import AgentDojoData
    from .splits import Splits

    splits = Splits(AgentDojoData(load_config(cfg_path).data_dir))
    cases, seen = [], set()
    for p in case_paths:
        for c in load_cases(p):
            if c.case_id not in seen:
                seen.add(c.case_id)
                cases.append(c)
    gold_rows = list(read_jsonl(gold_path))
    matched = attach_gold(cases, gold_rows)
    if matched < len(gold_rows):
        missing = sorted({g["case_id"] for g in gold_rows} - seen)
        raise SystemExit(f"{len(missing)} gold rows have no case: {missing[:5]}")
    labelled = [c for c in cases if c.has_gold]
    for c in labelled:
        splits.assert_pool(c, pool)
    n = save_cases(out, labelled)
    mix = Counter(c.gold_decision for c in labelled)
    print(f"froze {n} labelled {pool} cases -> {out}  gold first-round mix: {dict(mix)}")


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
    d.add_argument("--seed", type=int, default=42)
    fz = sub.add_parser("freeze")
    fz.add_argument("--cases", nargs="+", required=True, help="candidate case files (+ decision-only NL cases)")
    fz.add_argument("--gold", required=True)
    fz.add_argument("--pool", required=True, choices=["dev", "test"])
    fz.add_argument("--out", required=True)
    fz.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "export":
        export(a.cases, a.out, a.sample, a.seed)
    elif a.cmd == "agreement":
        print(json.dumps(agreement(a.csvs), indent=1))
    elif a.cmd == "gold":
        gold(a.adjudicated, a.out, a.seed)
    else:
        freeze(a.cases, a.gold, a.pool, a.out, a.config)


if __name__ == "__main__":
    main()
