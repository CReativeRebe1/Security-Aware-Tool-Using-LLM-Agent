# NB02 baselines: B1 (rules, CPU) + B2 / B3 (prompted Qwen3-8B, GPU0 / GPU1) on the test (and dev) cases.
# Cases: annotations/test_cases.jsonl if the annotated set exists in the staged code, else the test candidates
# built from the dataset (pre-annotation dry run; ScenarioResponder answers ASK_USER).
# Output: /kaggle/working/outputs/{cases,predictions}/
import glob
import os
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

OUT = "/kaggle/working/outputs"
POOLS = ["test", "dev"]
PROMPTED = ["b2_prompt_binary", "b3_prompt_4way"]
LIMIT = None            # e.g. 50 for a quick dry run

root = bootstrap.setup()
py = sys.executable
cases = {}
for pool in POOLS:
    annotated = os.path.join(root, "annotations", f"{pool}_cases.jsonl")
    if os.path.exists(annotated):
        cases[pool] = annotated
    else:
        cases[pool] = f"{OUT}/cases/{pool}_candidates.jsonl"
        bootstrap.run([py, "-m", "sagate.data.build_cases", "--pool", pool, "--out", cases[pool]])
    print(f"{pool} cases: {cases[pool]}", flush=True)

limit = ["--limit", str(LIMIT)] if LIMIT else []
for pool in POOLS:
    for responses in ("clean", "noisy"):          # B1 has the resolution loop too: clean vs noisy for every 4-way gate
        bootstrap.run([py, "-m", "sagate.eval.run_gate", "--condition", "b1_rules", "--cases", cases[pool],
                       "--pool", pool, "--responses", responses, "--out", f"{OUT}/predictions/{pool}"] + limit)


def job(cond, responses="clean"):
    # one GPU job = one condition over all pools (the model is loaded once per pool run; cache shared)
    cmds = [f"{py} -m sagate.eval.run_gate --condition {cond} --cases {cases[p]} --pool {p} "
            f"--responses {responses} --out {OUT}/predictions/{p} {' '.join(limit)}" for p in POOLS]
    return ["bash", "-c", " && ".join(cmds)]


codes = bootstrap.run_on_gpus([job(c) for c in PROMPTED])
codes += bootstrap.run_on_gpus([job("b3_prompt_4way", "noisy")])     # B2 has no resolution loop

for pool in POOLS:
    preds = sorted(glob.glob(f"{OUT}/predictions/{pool}/*.jsonl"))
    bootstrap.run([py, "-m", "sagate.eval.report", "--cases", cases[pool], "--pred", *preds,
                   "--json", f"{OUT}/predictions/{pool}/report.json"])
sys.exit(max(codes))
