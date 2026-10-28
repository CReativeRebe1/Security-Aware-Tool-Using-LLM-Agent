# NB03 QLoRA training: structured variants (train_only + dev pool) and per-condition SFT data are built on CPU, then
# the CONDITIONS are trained one GPU job per GPU (each job trains its share sequentially).
# Output: /kaggle/working/outputs/{sft/, adapters/<condition>/, checkpoints/<condition>/, logs/}
import glob
import os
import shutil
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

CONDITIONS = ["b5_qlora_4way", "b4_qlora_binary", "b5_no_prov", "b5_no_auth",     # primary first (H1/H2)
              "b5_no_rag", "b5_no_ask", "b5_no_esc", "b5_no_inter"]
NUM_GPUS = 2
MAX_STEPS = None        # e.g. 20 for a smoke run
OUT = "/kaggle/working/outputs"

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")   # long examples fragment T4 memory
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
bootstrap.run([py, "-m", "sagate.train.variants", "--pool", "train_only", "--out", f"{sft}/train_only_variants.jsonl"])
bootstrap.run([py, "-m", "sagate.train.variants", "--pool", "dev", "--out", f"{sft}/dev_cases.jsonl"])
train_cases = [f"{sft}/train_only_variants.jsonl"]
nl = os.path.join(root, "annotations", "train_nl.jsonl")
if os.path.exists(nl):
    train_cases.append(nl)
else:
    print("note: annotations/train_nl.jsonl not staged", flush=True)
synthetic_nl = os.path.join(root, "data", "labled-data", "synthetic_nl.jsonl")   # 2,000 labelled synthetic cases
if os.path.exists(synthetic_nl):
    train_cases.append(synthetic_nl)
else:
    print("note: data/labled-data/synthetic_nl.jsonl not staged", flush=True)
code = bootstrap.run([py, "-m", "sagate.train.build_sft", "--condition", *CONDITIONS, "--cases", *train_cases,
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
