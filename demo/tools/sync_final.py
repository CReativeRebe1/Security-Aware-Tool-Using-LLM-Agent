"""Copy the team's current final-gate results from main into demo/data/final/, without merging main.

The demo keeps its own frozen Run 1 code; the final gate's recorded predictions are added as one more gate, the same
way tools/sync_gateexp.py adds GateExp. Everything copied is listed in SOURCE.json with the commit it came from.

  python demo/tools/sync_final.py                 # the run the main README reports (defaults below)

Defaults follow main's README "Results" section (12 Nov): b5_v3_combo inside the GateExp layers, scored by the CPU
replay through the review fixes (dev, red-team attacks, factor combinations), plus the live AgentDojo run. When the
final b5_v4_combo results land, point --run / --cond / --e2e at them and run this again.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "demo" / "data" / "final"
POOLS = ("dev", "attacks", "combos")
# B0 (no gate) live AgentDojo numbers: docs/GATE_EVALUATION.md, "B0 (no gate, NB01)" row; same agent and scenarios.
B0 = {"utility": "49/142 (34.5%)", "attack_success_rate": "10/120 (8.3%)", "source": "docs/GATE_EVALUATION.md (NB01)"}
# Final training runs A-D (docs/TRAINING_RUNS.md): which branch holds each run's summaries.
TRAIN_RUNS = {"A": "origin/main", "B": "origin/run-b", "C": "origin/main", "D": "origin/run-d"}
TRAIN_FIELDS = ("condition", "examples", "kept", "global_step", "train_loss", "runtime_s", "seed", "peak_gpu_gb")
LABEL_FIELDS = ("gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority")


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(r.stderr.strip())
    return r.stdout if r.returncode == 0 else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--cond", default="b5_v3_combo_gateexp")
    ap.add_argument("--run", default="results/data/2026-11-12_replay_review_fixes",
                    help="folder with <cond>.<pool>.new.jsonl / .new.report.json (the README's numbers)")
    ap.add_argument("--e2e", default="results/data/2026-11-12_e2e_agentdojo_b5v3/report/e2e.json")
    a = ap.parse_args()
    commit = git("rev-parse", "--short", a.ref).strip()
    run_commit = git("log", "-1", "--format=%h", a.ref, "--", a.run).strip()     # cases as labelled for this run
    OUT.mkdir(parents=True, exist_ok=True)
    files = []
    for pool in POOLS:
        (OUT / pool).mkdir(exist_ok=True)
        for src, dst in ((f"{a.cond}.{pool}.new.jsonl", f"{a.cond}.jsonl"),
                         (f"{a.cond}.{pool}.new.report.json", f"{a.cond}.report.json")):
            (OUT / pool / dst).write_text(git("show", f"{a.ref}:{a.run}/{src}"))
            files.append(f"{a.run}/{src}")
    (OUT / "combo_cases.jsonl").write_text(git("show", f"{run_commit}:annotations/dev_combos.jsonl"))
    files.append(f"annotations/dev_combos.jsonl @ {run_commit}")
    # The team relabelled some dev cases after the freeze (new-payee / amount confirmations, policy step 2).
    # Keep only the differences from the frozen labels this branch uses, so the demo can say so per case.
    relabels = {}
    new = {json.loads(l)["input"]["case_id"]: json.loads(l)
           for l in git("show", f"{run_commit}:annotations/dev_cases.jsonl").splitlines() if l.strip()}
    with open(REPO / "annotations" / "dev_cases.jsonl") as f:
        for line in f:
            old = json.loads(line)
            cid = old["input"]["case_id"]
            diff = {k: [old.get(k), new[cid].get(k)] for k in LABEL_FIELDS if cid in new and old.get(k) != new[cid].get(k)}
            if diff:
                relabels[cid] = diff
    (OUT / "relabels.json").write_text(json.dumps(relabels, indent=1, ensure_ascii=False))
    files.append(f"annotations/dev_cases.jsonl @ {run_commit} (label differences only)")
    e2e = json.loads(git("show", f"{a.ref}:{a.e2e}"))
    (OUT / "e2e.json").write_text(json.dumps({"b0": B0, **e2e}, indent=1))
    files.append(a.e2e)

    runs = {}
    for letter, ref in TRAIN_RUNS.items():
        folder = f"results/data/2026-11-13_train_run_{letter.lower()}"
        names = [p for p in git("ls-tree", "--name-only", f"{ref}:{folder}", check=False).split() if
                 p.endswith(".train_summary.json")]
        models = []
        for n in names:
            s = json.loads(git("show", f"{ref}:{folder}/{n}"))
            models.append({k: s.get(k) for k in TRAIN_FIELDS})
        runs[letter] = {"branch": ref.replace("origin/", ""), "models": models}
        if models:
            files.append(f"{folder} ({ref})")
    (OUT / "training_runs.json").write_text(json.dumps(runs, indent=1))

    (OUT / "SOURCE.json").write_text(json.dumps({
        "branch_ref": a.ref, "commit": commit, "run_folder": a.run, "run_commit": run_commit, "condition": a.cond,
        "copied": files, "relabelled_dev_cases": len(relabels),
        "note": "Dev and red-team predictions are scored in the demo against the same labels as every other gate "
                "(frozen dev labels; red-team labels from GateExp). The combination cases keep the labels of the "
                "run's commit (generated by the team's rule oracle). The team's own reports are copied unchanged. "
                "The final gate has no test results on purpose: test is held back for one final run.",
    }, indent=1))
    print(f"copied {len(files)} items from {a.ref} ({commit}); run {a.run} @ {run_commit} -> {OUT}")
    for letter, r in runs.items():
        print(f"  training run {letter}: {[m['condition'] for m in r['models']] or 'not pushed yet'}")


if __name__ == "__main__":
    main()
