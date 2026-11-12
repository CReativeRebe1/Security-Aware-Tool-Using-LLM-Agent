# NB08 GateExp evaluation: trained B5 adapters (no training) inside the GateExp layers (docs/GATE_EVALUATION.md).
# Two GPUs; a job starts only while the 2 h budget lasts (a running job may finish).
#   one condition:   gpu0 dev -> combos -> test;  gpu1 attacks -> attacks noisy -> test noisy  (test last, run once)
#   two conditions:  one condition per GPU over POOLS, clean responses (model selection; leave "test" out of POOLS)
# Needs: <owner>/sagate-code + <owner>/sagate-b5-adapter (adapters/<name>/).
# Output: /kaggle/working/outputs/gateexp/<pool>/<condition>[_noisy].{jsonl,report.json,decision_log.jsonl}
import glob
import os
import sys
import time

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

CONDITIONS = ["b5_v3_combo_gateexp"]               # final gate; two names = side-by-side selection run
POOLS = ("dev", "combos", "attacks", "test")       # e.g. ("custom",) with CUSTOM for a user-supplied case file
CUSTOM = "user_cases_2026-11-12.jsonl"             # annotations/extra/<CUSTOM>
ADAPTERS = {"b5_gateexp": "b5_qlora_4way", "b5_v2_gateexp": "b5_v2", "b5_v3_gateexp": "b5_v3",
            "b5_v3_combo_gateexp": "b5_v3_combo"}
BUDGET_S = 2 * 3600
LIMIT = None                                       # e.g. 20 for a quick dry run
OUT = "/kaggle/working/outputs/gateexp"
t_end = int(time.time()) + BUDGET_S

root = bootstrap.setup()
py = sys.executable
adapters = bootstrap.collect_adapters()
for c in CONDITIONS:
    if not adapters or not os.path.exists(f"{adapters}/{ADAPTERS[c]}"):
        sys.exit(f"adapter not attached (no {ADAPTERS[c]} under /kaggle/input)")
cases = {"dev": os.path.join(root, "annotations", "dev_cases.jsonl"),
         "combos": os.path.join(root, "annotations", "dev_combos.jsonl"),     # held-out factor combinations
         "attacks": os.path.join(root, "annotations", "attack_cases.jsonl"),
         "test": os.path.join(root, "annotations", "test_cases.jsonl"),
         "custom": os.path.join(root, "annotations", "extra", CUSTOM)}
cases = {k: v for k, v in cases.items() if k in POOLS and os.path.exists(v)}
print("case files:", {k: os.path.basename(v) for k, v in cases.items()}, flush=True)
limit = f" --limit {LIMIT}" if LIMIT else ""


def job(cond, pool, responses="clean"):
    if pool not in cases:
        return None
    split = "dev" if pool in ("dev", "combos") else "test"       # attack and custom cases carry no split tag
    cmd = (f"{py} -m sagate.eval.run_gate --condition {cond} --cases {cases[pool]} --pool {split} "
           f"--responses {responses} --adapter-dir {adapters} --out {OUT}/{pool}{limit}")
    # skip when the budget is spent; a job that already started is allowed to finish
    return f'if [ "$(date +%s)" -lt {t_end} ]; then {cmd}; else echo "budget spent: skip {cond} {pool} {responses}"; fi'


if len(CONDITIONS) == 2:
    gpus = [[job(c, p) for p in POOLS] for c in CONDITIONS]
else:
    c = CONDITIONS[0]
    gpus = [[job(c, "dev"), job(c, "combos"), job(c, "custom"), job(c, "test")],
            [job(c, "attacks"), job(c, "attacks", "noisy"), job(c, "custom", "noisy"), job(c, "test", "noisy")]]
gpus = [[j for j in g if j] for g in gpus]
codes = bootstrap.run_on_gpus([["bash", "-c", " ; ".join(g)] for g in gpus if g])

for pool, path in cases.items():
    for c in CONDITIONS:
        for pred in sorted(glob.glob(f"{OUT}/{pool}/{c}.jsonl") + glob.glob(f"{OUT}/{pool}/{c}_noisy.jsonl")):
            name = os.path.basename(pred)[:-6]
            bootstrap.run([py, "-m", "sagate.eval.gateexp_report", "report", "--pred", pred, "--cases", path,
                           "--json", f"{OUT}/{pool}/{name}.report.json"])
            bootstrap.run([py, "-m", "sagate.eval.gateexp_report", "log", "--pred", pred, "--cases", path,
                           "--out", f"{OUT}/{pool}/{name}.decision_log.jsonl"])
print(f"elapsed {(time.time() - (t_end - BUDGET_S)) / 60:.0f} min", flush=True)
sys.exit(max(codes))
