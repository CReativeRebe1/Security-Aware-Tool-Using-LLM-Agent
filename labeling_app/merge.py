#!/usr/bin/env python3
"""Build the label database from everyone's review files, per phase and combined.

    git pull                       # get everyone's annotations/<name>/<batch>.json
    python labeling_app/merge.py   # -> data/synthetic_data/labels/

Writes (all derived, safe to regenerate):
  labels/phase_1/   the 10 batches of phase 1
  labels/phase_2/   the 10 batches of phase 2
  labels/combined/  all 20 batches together (after phase 1 this is phase 1's data; after phase 2, everything)
  labels/summary.json   progress of each phase and whether it is finished

Each folder holds:
  votes.jsonl         every review, one per line
  cases.jsonl         every case: phase, batch, status, its two reviewers, and the gold labels once agreed
  gold.jsonl          only agreed cases, ready for the training/eval pipeline
  disputed.json       cases where the two reviewers disagree, per batch (the pair settles them)
  cannot_label.json   cases both reviewers marked "can't label", with their reasons and notes
  agreement.json      Krippendorff's alpha (nominal) and Cohen's kappa between the two reviewers
  label_mix.json      gold decisions, final actions, suites and categories, to compare the phases
Status: unlabeled | partial | agreed | disputed | cannot_label.
A phase is finished when every case in it is agreed or cannot_label.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labels as L  # noqa: E402

STATUSES = ("unlabeled", "partial", "agreed", "disputed", "cannot_label")


def krippendorff_alpha(units: list[list]) -> float | None:
    """Nominal alpha; each unit is the list of values different coders gave one item (missing values omitted)."""
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    coinc: Counter = Counter()
    for u in units:
        m = len(u)
        for i, j in ((i, j) for i in range(m) for j in range(m) if i != j):
            coinc[(u[i], u[j])] += 1 / (m - 1)
    n_c: Counter = Counter()
    for (a, _), w in coinc.items():
        n_c[a] += w
    n = sum(n_c.values())
    d_o = sum(w for (a, b), w in coinc.items() if a != b)
    d_e = sum(n_c[a] * n_c[b] for a in n_c for b in n_c if a != b) / (n - 1)
    return 1.0 if d_e == 0 else 1 - d_o / d_e


def cohen_kappa(x: list, y: list) -> float | None:
    if not x:
        return None
    n = len(x)
    po = sum(a == b for a, b in zip(x, y)) / n
    cx, cy = Counter(x), Counter(y)
    pe = sum(cx[k] * cy[k] for k in cx) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def build(asg: dict, batch_ids: list[str], out_dir: Path) -> Counter:
    """Merge the reviews of the given batches into out_dir; returns the case count per status."""
    out_dir.mkdir(parents=True, exist_ok=True)
    votes, cases, gold = [], [], []
    disputed, cant = defaultdict(list), defaultdict(list)
    pairs = defaultdict(lambda: defaultdict(lambda: ([], [])))      # field -> (a, b) -> (a's, b's labels)
    units = defaultdict(list)                                         # field -> [[a's, b's]]
    status_count: Counter = Counter()
    mix = defaultdict(Counter)

    for bid in batch_ids:
        b = asg["batches"][bid]
        ra, rb = b["reviewers"]
        va, vb = L.read_votes(ra, bid), L.read_votes(rb, bid)
        votes += [*va.values(), *vb.values()]
        for case in L.load_batch(bid):
            cid = case["case_id"]
            p1, p2 = va.get(cid), vb.get(cid)
            status, g = L.resolve(p1, p2)
            status_count[status] += 1
            meta = {"case_id": cid, "phase": b["phase"], "batch_id": bid}
            cases.append({**meta, "status": status, "reviewers": [ra, rb], **(g or {})})
            if g:
                gold.append({**meta, "suite": case.get("suite"), "category": case.get("category"), **g})
                mix["gold_decision"][g["gold_decision"]] += 1
                mix["gold_final_action"][g["gold_final_action"]] += 1
                mix["suite"][case.get("suite")] += 1
                mix["category"][case.get("category")] += 1
            elif status == "disputed":
                disputed[f"{bid} ({ra}, {rb})"].append(cid)
            elif status == "cannot_label":
                cant[bid].append({"case_id": cid, "reasons": {v["annotator"]: {
                    "reason": v["review"].get("reason"), "note": v["review"].get("note")} for v in (p1, p2)}})
            if L.is_complete(p1) and L.is_complete(p2):
                for f in L.AGREEMENT_FIELDS:
                    units[f].append([p1[f], p2[f]])
                    xs, ys = pairs[f][(ra, rb)]
                    xs.append(p1[f])
                    ys.append(p2[f])

    agreement = {}
    for f in L.AGREEMENT_FIELDS:
        u = units[f]
        agreement[f] = {
            "n_cases": len(u),
            "percent_agreement": (sum(x == y for x, y in u) / len(u)) if u else None,
            "krippendorff_alpha": krippendorff_alpha(u),
            "cohen_kappa": {f"{a}-{b}": {"n": len(xs), "kappa": cohen_kappa(xs, ys)}
                            for (a, b), (xs, ys) in sorted(pairs[f].items())},
        }

    def dump_jsonl(name, rows):
        with open(out_dir / name, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def dump_json(name, data):
        (out_dir / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    dump_jsonl("votes.jsonl", sorted(votes, key=lambda v: (v["case_id"], v["annotator"])))
    dump_jsonl("cases.jsonl", cases)
    dump_jsonl("gold.jsonl", gold)
    dump_json("disputed.json", dict(disputed))
    dump_json("cannot_label.json", dict(cant))
    dump_json("agreement.json", agreement)
    dump_json("label_mix.json", {k: dict(sorted(v.items())) for k, v in mix.items()})
    return status_count


def main() -> None:
    asg = L.load_assignments()
    root = L.LABELS_DIR
    summary = {}
    for ph in L.PHASES:
        bids = L.phase_batches(asg, ph)
        c = build(asg, bids, root / f"phase_{ph}")
        total = sum(c.values())
        summary[f"phase_{ph}"] = {"batches": bids, "cases": total, **{s: c[s] for s in STATUSES},
                                  "finished": c["agreed"] + c["cannot_label"] == total}
    c = build(asg, sorted(asg["batches"]), root / "combined")
    summary["combined"] = {"cases": sum(c.values()), **{s: c[s] for s in STATUSES}}
    (root / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    print(f"-> {root}")
    print(f"  {'':10s}" + "".join(f"{s:>14s}" for s in STATUSES) + "    finished")
    for name, s in summary.items():
        done = "" if name == "combined" else ("yes" if s["finished"] else "no")
        print(f"  {name:10s}" + "".join(f"{s[k]:>14d}" for k in STATUSES) + f"    {done}")
    alpha = json.loads((root / "combined" / "agreement.json").read_text())["gold_decision"]["krippendorff_alpha"]
    print(f"  alpha on the decision (combined): {'n/a' if alpha is None else f'{alpha:.3f}'}")
    if summary["combined"]["disputed"]:
        print("  disputed cases: the two reviewers should talk and revise their own reviews (see */disputed.json)")


if __name__ == "__main__":
    main()
