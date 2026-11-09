#!/usr/bin/env python3
"""Freeze the train / validation / test split of the human-labelled cases.

    python human_label_dataset/freeze_split.py

The split is by scenario family: every case of a family (its variants, prompt paraphrases and answered rounds)
lands in one split, so no near-copy of a test case is ever trained on. Families are assigned once, with a fixed
seed and a search for the assignment whose label mix is closest across the three splits, and the assignment is
saved in splits/family_split.json. Later runs reuse that file, so the split never moves: cases reviewed later
join the split their family already has.

Writes human_label_dataset/splits/:
  family_split.json     family -> train | dev | test   (the frozen assignment)
  train.jsonl, dev.jsonl, test.jsonl
                        final labelled cases, each tagged with `pool` (the tag the pipeline's leakage guard reads)
  not_reviewed.json     cases without a usable human label yet, per split (added after review, never moved)
  MANIFEST.json         sources, seed, counts, label mixes and sha256 of every file
  SPLITS.md             the same, readable
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "labeling_app"))
import labels as L  # noqa: E402

SEED = 42
TARGET = {"train": 0.70, "dev": 0.15, "test": 0.15}
USE_TIERS = {"A", "B", "T"}             # tier C (only fast, unconfirmed reviews) is left out
MIN_TEST_ESCALATE = 30                  # the test set must be able to measure escalation
SEARCH = 20000
OUT = HERE / "splits"
DECISIONS = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")


def all_cases() -> dict[str, dict]:
    out = {}
    for b in sorted(L.load_assignments()["batches"]):
        for c in L.load_batch(b):
            out[c["case_id"]] = {"family": c["raw_case"]["meta"]["family"], "suite": c["suite"],
                                 "category": c["category"], "batch_id": b}
    return out


def assign(cases: dict, labels: dict) -> dict[str, str]:
    """Search family assignments; keep the one closest to the target sizes and to the overall label mix."""
    fam = defaultdict(list)
    for cid, c in cases.items():
        fam[c["family"]].append(cid)
    fams = sorted(fam)

    def mix(cids):
        dec = Counter(labels[c]["gold_decision"] for c in cids if c in labels)
        cat = Counter(cases[c]["category"] for c in cids)
        suite = Counter(cases[c]["suite"] for c in cids)
        return dec, cat, suite

    tot_dec, tot_cat, tot_suite = mix(list(cases))
    n_all, n_lab = len(cases), sum(tot_dec.values())
    rng = random.Random(SEED)
    best, best_score = None, None
    for _ in range(SEARCH):
        order = fams[:]
        rng.shuffle(order)
        split, size = {}, Counter()
        for f in order:                                  # greedy fill towards the target sizes
            need = {s: TARGET[s] * n_all - size[s] for s in TARGET}
            s = max(need, key=need.get)
            split[f] = s
            size[s] += len(fam[f])
        groups = {s: [c for f in fams if split[f] == s for c in fam[f]] for s in TARGET}
        dec_test = mix(groups["test"])[0]
        if dec_test["ESCALATE"] < MIN_TEST_ESCALATE:
            continue
        score = 0.0
        for s, cids in groups.items():
            dec, cat, suite = mix(cids)
            n = len(cids)
            nl = sum(dec.values()) or 1
            score += abs(n / n_all - TARGET[s]) * 4
            score += sum(abs(dec[d] / nl - tot_dec[d] / n_lab) for d in DECISIONS)
            score += sum(abs(cat[k] / n - tot_cat[k] / n_all) for k in tot_cat) * 0.5
            score += sum(abs(suite[k] / n - tot_suite[k] / n_all) for k in tot_suite) * 0.5
            missing = [k for k in tot_cat if cat[k] == 0]
            score += len(missing) * 0.5                  # every category in every split if possible
        if best_score is None or score < best_score:
            best, best_score = split, score
    if best is None:
        raise SystemExit("no assignment met the test ESCALATE minimum")
    return best


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cases = all_cases()
    rows = [json.loads(x) for x in open(HERE / "final" / "human_labels.jsonl", encoding="utf-8")]
    labels = {r["case_id"]: r for r in rows if r["tier"] in USE_TIERS}

    fs_path = OUT / "family_split.json"
    if fs_path.exists():
        family_split = json.loads(fs_path.read_text(encoding="utf-8"))["families"]
        new = {c["family"] for c in cases.values()} - set(family_split)
        if new:
            raise SystemExit(f"families not in the frozen split: {sorted(new)}")
    else:
        family_split = dict(sorted(assign(cases, labels).items()))
        fs_path.write_text(json.dumps({"seed": SEED, "target": TARGET, "families": family_split}, indent=1),
                           encoding="utf-8")

    out = {s: [] for s in TARGET}
    not_reviewed = {s: [] for s in TARGET}
    for cid, c in cases.items():
        s = family_split[c["family"]]
        if cid in labels:
            out[s].append({**labels[cid], "pool": s, "family": c["family"]})
        else:
            not_reviewed[s].append(cid)
    for s, rs in out.items():
        rs.sort(key=lambda r: r["case_id"])
        with open(OUT / f"{s}.jsonl", "w", encoding="utf-8") as fh:
            for r in rs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "not_reviewed.json").write_text(json.dumps({s: sorted(v) for s, v in not_reviewed.items()}, indent=1),
                                           encoding="utf-8")

    # leakage checks
    fam_of = {s: {r["family"] for r in rs} for s, rs in out.items()}
    assert not (fam_of["train"] & fam_of["dev"]) and not (fam_of["train"] & fam_of["test"]) \
        and not (fam_of["dev"] & fam_of["test"]), "a family is in two splits"
    ids = [r["case_id"] for rs in out.values() for r in rs]
    assert len(ids) == len(set(ids)), "a case is in two splits"

    def summary(rs):
        return {"cases": len(rs), "families": len({r["family"] for r in rs}),
                "gold_decision": {d: sum(r["gold_decision"] == d for r in rs) for d in DECISIONS},
                "gold_final_action": dict(Counter(r["gold_final_action"] for r in rs)),
                "suite": dict(Counter(r["suite"] for r in rs)),
                "category": dict(sorted(Counter(r["category"] for r in rs).items())),
                "answered_round": sum(r["round"] == 1 for r in rs),
                "tier": dict(sorted(Counter(r["tier"] for r in rs).items()))}

    manifest = {
        "seed": SEED, "split_by": "scenario family", "target_share": TARGET, "tiers_used": sorted(USE_TIERS),
        "source": {"labeling_branch_reviews": "data/synthetic_data/batches/annotations (labeling @ a4d3bd2)",
                   "human_label_dataset_commit": git_head()},
        "splits": {s: summary(rs) for s, rs in out.items()},
        "not_reviewed": {s: len(v) for s, v in not_reviewed.items()},
        "files": {p.name: sha(p) for p in sorted(OUT.glob("*")) if p.name not in ("MANIFEST.json", "SPLITS.md")},
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    write_md(manifest)
    print(json.dumps({s: {k: v[k] for k in ("cases", "families", "gold_decision")} for s, v in manifest["splits"].items()},
                     indent=1))
    print("not reviewed:", manifest["not_reviewed"])


def write_md(m: dict) -> None:
    S = m["splits"]
    cats = sorted({k for s in S.values() for k in s["category"]})
    lines = [
        "# Frozen split",
        "",
        f"Split by scenario family (seed {m['seed']}): every case of a family is in one split, so no paraphrase or"
        " answered round of a test situation is ever trained on. The family assignment is frozen in"
        " `family_split.json`; rerunning `freeze_split.py` reuses it.",
        "",
        "| | Train | Dev (validation) | Test |",
        "|---|---|---|---|",
        "| Cases | " + " | ".join(str(S[s]["cases"]) for s in ("train", "dev", "test")) + " |",
        "| Families | " + " | ".join(str(S[s]["families"]) for s in ("train", "dev", "test")) + " |",
        *[f"| {d} | " + " | ".join(str(S[s]["gold_decision"][d]) for s in ("train", "dev", "test")) + " |" for d in DECISIONS],
        "| Final ALLOW / BLOCK | " + " | ".join(f"{S[s]['gold_final_action'].get('ALLOW', 0)} / {S[s]['gold_final_action'].get('BLOCK', 0)}"
                                          for s in ("train", "dev", "test")) + " |",
        "| Banking / workspace | " + " | ".join(f"{S[s]['suite'].get('banking', 0)} / {S[s]['suite'].get('workspace', 0)}"
                                          for s in ("train", "dev", "test")) + " |",
        "| Answered-round cases | " + " | ".join(str(S[s]["answered_round"]) for s in ("train", "dev", "test")) + " |",
        "| Not reviewed yet (join later) | " + " | ".join(str(m["not_reviewed"][s]) for s in ("train", "dev", "test")) + " |",
        "",
        "| Category | Train | Dev | Test |",
        "|---|---|---|---|",
        *[f"| {c.replace('_', ' ')} | " + " | ".join(str(S[s]["category"].get(c, 0)) for s in ("train", "dev", "test")) + " |" for c in cats],
        "",
        "Every row carries `pool` (`train`, `dev` or `test`), the tag the pipeline's leakage guard checks on"
        " decision-only cases. Only tiers A, B and T are used; the 2 tier-C cases wait for a careful review.",
        "",
        "File hashes are in `MANIFEST.json`.",
    ]
    (OUT / "SPLITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
