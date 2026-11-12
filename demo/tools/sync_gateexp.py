"""Copy one GateExp run from the GateExp branch into demo/data/gateexp/, without merging the branch.

The demo stays on the frozen Run 1 code and labels; GateExp's predictions are added as one more recorded gate.
Everything copied is listed in SOURCE.json with the commit it came from.

  python demo/tools/sync_gateexp.py                      # defaults below
  python demo/tools/sync_gateexp.py --ref origin/GateExp --run results/data/2026-11-12_gateexp_tags_ab_b5v2/tags
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "demo" / "data" / "gateexp"
COND = "b5_v2_gateexp"
POOLS = ("test", "dev", "attacks")
LABEL_FIELDS = ("gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority")


def git_show(ref: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/GateExp")
    ap.add_argument("--run", default="results/data/2026-11-12_gateexp_tags_ab_b5v2/tags",
                    help="the run folder the GateExp README calls current")
    a = ap.parse_args()
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", a.ref], check=True, capture_output=True,
                            text=True).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    files = []
    for pool in POOLS:
        (OUT / pool).mkdir(exist_ok=True)
        for suffix in (".jsonl", ".report.json", ".manifest.json"):
            rel = f"{a.run}/{pool}/{COND}{suffix}"
            (OUT / pool / f"{COND}{suffix}").write_text(git_show(a.ref, rel))
            files.append(rel)
    (OUT / "attack_cases.jsonl").write_text(git_show(a.ref, "annotations/attack_cases.jsonl"))
    files.append("annotations/attack_cases.jsonl")

    # GateExp relabelled some frozen cases. Keep only the differences, so the demo can say so per case.
    relabels = {}
    for split in ("test", "dev"):
        new = {json.loads(l)["input"]["case_id"]: json.loads(l)
               for l in git_show(a.ref, f"annotations/{split}_cases.jsonl").splitlines() if l.strip()}
        with open(REPO / "annotations" / f"{split}_cases.jsonl") as f:
            for line in f:
                old = json.loads(line)
                cid = old["input"]["case_id"]
                diff = {k: [old.get(k), new[cid].get(k)] for k in LABEL_FIELDS if cid in new and old.get(k) != new[cid].get(k)}
                if diff:
                    relabels[cid] = diff
        files.append(f"annotations/{split}_cases.jsonl (label differences only)")
    (OUT / "relabels.json").write_text(json.dumps(relabels, indent=1, ensure_ascii=False))
    (OUT / "SOURCE.json").write_text(json.dumps({
        "branch_ref": a.ref, "commit": commit, "run_folder": a.run, "condition": COND,
        "copied": files, "relabelled_cases": len(relabels),
        "note": "Predictions are scored in the demo against the frozen labels (annotations/*_cases.jsonl on this "
                "branch). GateExp's own reports, made with its revised labels, are copied unchanged.",
    }, indent=1))
    print(f"copied {len(files)} files from {a.ref} ({commit}); {len(relabels)} relabelled cases -> {OUT}")


if __name__ == "__main__":
    main()
