# NB03 QLoRA training: structured variants (train_only + dev pool) and per-condition SFT data are built on CPU, then
# the CONDITIONS are trained one GPU job per GPU (each job trains its share sequentially).
# Output: /kaggle/working/outputs/{sft/, adapters/<condition>/, checkpoints/<condition>/, logs/}
import glob
import os
import shutil
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

# One group per Kaggle account, so teammates can train in parallel (docs/RUN_GUIDE.md). A = the primary run.
GROUPS = {"V2": ["b5_v2"],        # retrained B5: + annotations/train_augmented.jsonl, 1 epoch, weighted loss
          "V3": ["b5_v3", "b5_v3_combo"],   # retrain, one per GPU: prepared data / + factor-combination data
          "V4": ["b5_v4", "b5_v4_combo"],   # review-2 retrain: new clauses, relabelled data, no generated variants
          # final runs on the b5_v4_combo data and recipe (docs/TRAINING_RUNS.md), one per GPU:
          "A": ["b4_v4_binary_combo", "b5_v4_no_inter"],
          "B": ["b5_v4_no_prov", "b5_v4_no_auth"],
          "C": ["b5_v4_no_rag", "b5_v4_no_ask"],
          "D": ["b5_v4_no_esc", "b5_v4_combo_seed2"]}
# the first-round groups (b5_qlora_4way, b4_qlora_binary, b5_no_*) are in git history; their results are archived
GROUP = "C"                      # A | B | C | D (docs/TRAINING_RUNS.md); V4 = the B5 run
VARIANTS = False                  # add the ~1,000 generated variants (old runs: True)
CONDITIONS = GROUPS[GROUP]
NUM_GPUS = 2
MAX_STEPS = None        # e.g. 20 for a smoke run
OUT = "/kaggle/working/outputs"

root = bootstrap.setup("gpu,train")
py = sys.executable
# Resume (ARCHITECTURE.md §9.3): adapters/checkpoints of an earlier run, attached as "sagate-progress-nb03", are
# copied in first; finished adapters are skipped and unfinished runs resume from their latest checkpoint.
for kind in ("adapters", "checkpoints"):
    for prev in glob.glob(f"/kaggle/input/**/sagate-progress-nb03/**/{kind}/*", recursive=True):
        dest = os.path.join(OUT, kind, os.path.basename(prev))
        if os.path.isdir(prev) and not os.path.exists(dest):
            print("resuming from", prev, flush=True)
            shutil.copytree(prev, dest)

sft = f"{OUT}/sft"
bootstrap.run([py, "-m", "sagate.train.variants", "--pool", "dev", "--out", f"{sft}/dev_cases.jsonl"])   # B4 threshold
train_cases = []
if VARIANTS:     # rule-labelled variants agree with the human gold on only ~79% of train_human: off since review 2
    bootstrap.run([py, "-m", "sagate.train.variants", "--pool", "train_only", "--out", f"{sft}/train_only_variants.jsonl"])
    train_cases.append(f"{sft}/train_only_variants.jsonl")
nl = os.path.join(root, "annotations", "train_nl.jsonl")
if os.path.exists(nl):
    train_cases.append(nl)
else:
    print("note: annotations/train_nl.jsonl not staged", flush=True)
human = os.path.join(root, "annotations", "train_human.jsonl")    # frozen human-labelled training split
if not os.path.exists(human):
    sys.exit("annotations/train_human.jsonl not staged (python -m sagate.data.human_labels)")
train_cases.append(human)
train_cases.append(  # rule-based copies of the human cases (sagate.train.augment), every group since V2
    os.path.join(root, "annotations", "train_augmented.jsonl"))
print(f"group {GROUP}: {CONDITIONS}", flush=True)
# one SFT build per condition; train.extra_cases (e.g. the factor-combination data) are added to that condition only
import yaml  # noqa: E402

for c in CONDITIONS:
    with open(os.path.join(root, "configs", "conditions", f"{c}.yaml")) as f:
        extra = [os.path.join(root, x) for x in ((yaml.safe_load(f) or {}).get("train") or {}).get("extra_cases", [])]
    missing_extra = [x for x in extra if not os.path.exists(x)]
    if missing_extra:
        sys.exit(f"{c}: extra cases not staged: {missing_extra}")
    code = bootstrap.run([py, "-m", "sagate.train.build_sft", "--condition", c, "--cases", *train_cases, *extra,
                          "--out", sft])
    if code:
        sys.exit(code)

todo = [c for c in CONDITIONS if not os.path.exists(f"{OUT}/adapters/{c}/train_summary.json")]
print("to train:", todo, flush=True)
steps = f" --max-steps {MAX_STEPS}" if MAX_STEPS else ""
jobs = []
for g in range(NUM_GPUS):
    mine = todo[g::NUM_GPUS]
    if mine:
        cmds = [f"{py} -m sagate.train.train_qlora --condition {c} --sft {sft}/{c}.jsonl --out {OUT}{steps}"
                for c in mine]
        jobs.append(["bash", "-c", " ; ".join(cmds)])      # one failed run does not stop the others
codes = bootstrap.run_on_gpus(jobs) if jobs else [0]
missing = [c for c in CONDITIONS if not os.path.exists(f"{OUT}/adapters/{c}/train_summary.json")]
print("adapters missing:", missing or "none", flush=True)
# checkpoints are only needed to resume; drop them for finished adapters to keep the output small
for c in CONDITIONS:
    if c not in missing:
        shutil.rmtree(f"{OUT}/checkpoints/{c}", ignore_errors=True)
sys.exit(1 if missing else max(codes))
