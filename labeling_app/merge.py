#!/usr/bin/env python3
"""Build the main label database from everyone's vote files.

    git pull                       # get everyone's annotations/<name>/<batch>.json
    python labeling_app/merge.py   # -> data/synthetic_data/labels/

Writes (all derived, safe to regenerate):
  votes.jsonl           every vote, one per line
  cases.jsonl           every case: batch, status, the votes' annotators, and the gold labels once decided
  gold.jsonl            only decided cases (status agreed or resolved), ready for the training/eval pipeline
  tiebreak_queue.json   disputed cases still waiting for their tie-break vote, per batch and tie-breaker
  agreement.json        Krippendorff's alpha (nominal) and pairwise Cohen's kappa on the two primary votes
Status: unlabeled | partial | agreed | awaiting_tiebreak | resolved | unresolved (three different votes).
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labels as L  # noqa: E402


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


def main() -> None:
    asg = L.load_assignments()
    out_dir = L.LABELS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    votes, cases, gold, queue = [], [], [], defaultdict(list)
    pairs = defaultdict(lambda: defaultdict(lambda: ([], [])))      # field -> (a, b) -> (a's, b's labels)
    units = defaultdict(list)                                         # field -> [[a's, b's]]
    status_count: Counter = Counter()

    for bid, b in sorted(asg["batches"].items()):
        a, c = b["primary"]
        tb = b["tiebreak"]
        va, vc, vt = L.read_votes(a, bid), L.read_votes(c, bid), L.read_votes(tb, bid)
        votes += [*va.values(), *vc.values(), *vt.values()]
        for case in L.load_batch(bid):
            cid = case["case_id"]
            p1, p2, t = va.get(cid), vc.get(cid), vt.get(cid)
            status, g = L.resolve([p1, p2], t)
            status_count[status] += 1
            row = {"case_id": cid, "batch_id": bid, "status": status,
                   "voters": [v["annotator"] for v in (p1, p2, t) if v], **(g or {})}
            cases.append(row)
            if g:
                gold.append({"case_id": cid, "batch_id": bid, "status": status, **g})
            if status == "awaiting_tiebreak":
                queue[f"{bid} ({tb})"].append(cid)
            if L.is_complete(p1) and L.is_complete(p2):
                for f in L.AGREEMENT_FIELDS:
                    units[f].append([p1[f], p2[f]])
                    xs, ys = pairs[f][(a, c)]
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

    dump_jsonl("votes.jsonl", sorted(votes, key=lambda v: (v["case_id"], v["annotator"])))
    dump_jsonl("cases.jsonl", cases)
    dump_jsonl("gold.jsonl", gold)
    (out_dir / "tiebreak_queue.json").write_text(json.dumps(dict(queue), indent=1), encoding="utf-8")
    (out_dir / "agreement.json").write_text(json.dumps(agreement, indent=1), encoding="utf-8")

    print(f"{len(votes)} votes on {len(cases)} cases -> {out_dir}")
    for s in ("unlabeled", "partial", "agreed", "awaiting_tiebreak", "resolved", "unresolved"):
        print(f"  {s:18s} {status_count[s]}")
    for f, r in agreement.items():
        alpha = "n/a" if r["krippendorff_alpha"] is None else f"{r['krippendorff_alpha']:.3f}"
        print(f"  alpha {f:24s} {alpha}  (n={r['n_cases']})")
    if status_count["unresolved"]:
        print("  unresolved cases (three different votes) need a team decision: see cases.jsonl")


if __name__ == "__main__":
    main()
