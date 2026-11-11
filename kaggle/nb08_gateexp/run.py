# NB08 GateExp: B5 adapter (no training) inside the GateExp layers (docs/GATE_EVALUATION.md §3).
# Jobs in priority order, two GPUs; a job starts only while the 2 h budget lasts (a running job may finish).
#   run 1 (b5_gateexp):    gpu0 test -> attacks -> dev;  gpu1 test noisy -> attacks noisy
#   b5_v2_gateexp:         gpu0 dev -> test;             gpu1 attacks -> attacks noisy -> test noisy
# Needs: <owner>/sagate-code dataset + the NB03 kernel with adapters/b5_qlora_4way (shared with this account).
# Output: /kaggle/working/outputs/gateexp/{test,dev,attacks}/ predictions, report.json, decision_log.jsonl
import glob
import os
import sys
import time

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

BUDGET_S = 2 * 3600
LIMIT = None            # e.g. 20 for a quick dry run
POOLS = ("test", "attacks", "dev")   # set to ("attacks",) to rerun only the attack cases
COND = "b5_v2_gateexp"              # b5_gateexp = run 1 adapter; b5_v2_gateexp / b5_v3_gateexp = retrained adapters
ADAPTER = {"b5_v2_gateexp": "b5_v2", "b5_v3_gateexp": "b5_v3", "b5_v3_nt_gateexp": "b5_v3_nt"}.get(COND, "b5_qlora_4way")
TAGS_AB = True                      # retrieval A/B: gpu0 without the clause coverage tags, gpu1 with them (clean only)
OUT = "/kaggle/working/outputs/gateexp"
t_end = int(time.time()) + BUDGET_S

root = bootstrap.setup()
py = sys.executable
adapters = bootstrap.collect_adapters()
if not adapters or not os.path.exists(f"{adapters}/{ADAPTER}"):
    sys.exit(f"adapter not attached (no {ADAPTER} under /kaggle/input)")
cases = {"test": os.path.join(root, "annotations", "test_cases.jsonl"),
         "dev": os.path.join(root, "annotations", "dev_cases.jsonl"),
         "attacks": os.path.join(root, "annotations", "attack_cases.jsonl")}
cases = {k: v for k, v in cases.items() if os.path.exists(v)}
print("case files:", {k: os.path.basename(v) for k, v in cases.items()}, flush=True)
limit = f" --limit {LIMIT}" if LIMIT else ""


def job(pool, responses="clean", tags=None):
    if pool not in cases or pool not in POOLS:
        return None
    env, out = ("SAGATE_RAG_TAGS=0 " if "_nt" in COND else ""), f"{OUT}/{pool}"
    if tags is not None:
        env, out = f"SAGATE_RAG_TAGS={int(tags)} ", f"{OUT}/{'tags' if tags else 'notags'}/{pool}"
    cmd = (f"{env}{py} -m sagate.eval.run_gate --condition {COND} --cases {cases[pool]} "
           f"--pool {'test' if pool == 'attacks' else pool} --responses {responses} --adapter-dir {adapters} "
           f"--out {out}{limit}")
    # skip when the budget is spent; a job that already started is allowed to finish
    return f'if [ "$(date +%s)" -lt {t_end} ]; then {cmd}; else echo "budget spent: skip {pool} {responses}"; fi'


if TAGS_AB:
    gpu0 = [j for j in (job("dev", tags=False), job("attacks", tags=False), job("test", tags=False)) if j]
    gpu1 = [j for j in (job("dev", tags=True), job("attacks", tags=True), job("test", tags=True)) if j]
elif COND in ("b5_v2_gateexp", "b5_v3_gateexp", "b5_v3_nt_gateexp"):   # dev and attacks first; test once at the end
    gpu0 = [j for j in (job("dev"), job("test")) if j]
    gpu1 = [j for j in (job("attacks"), job("attacks", "noisy"), job("test", "noisy")) if j]
else:
    gpu0 = [j for j in (job("test"), job("attacks"), job("dev")) if j]
    gpu1 = [j for j in (job("test", "noisy"), job("attacks", "noisy")) if j]
codes = bootstrap.run_on_gpus([["bash", "-c", " ; ".join(gpu0)], ["bash", "-c", " ; ".join(gpu1)]])

for pool, path in cases.items():
    for base in ((f"{OUT}/notags/{pool}", f"{OUT}/tags/{pool}") if TAGS_AB else (f"{OUT}/{pool}",)):
        for pred in sorted(glob.glob(f"{base}/{COND}*.jsonl")):
            name = os.path.basename(pred)[:-6]
            bootstrap.run([py, "-m", "sagate.eval.gateexp_report", "report", "--pred", pred, "--cases", path,
                           "--json", f"{base}/{name}.report.json"])
            bootstrap.run([py, "-m", "sagate.eval.gateexp_report", "log", "--pred", pred, "--cases", path,
                           "--out", f"{base}/{name}.decision_log.jsonl"])
print(f"elapsed {(time.time() - (t_end - BUDGET_S)) / 60:.0f} min", flush=True)
sys.exit(max(codes))
