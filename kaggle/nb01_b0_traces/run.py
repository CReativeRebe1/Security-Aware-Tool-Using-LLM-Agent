# NB01 B0 traces: Qwen3-8B agent (no gate) over the 418 strict train/test scenarios, sharded over 2 GPUs.
# Output: /kaggle/working/outputs/b0_traces/{traces_shard*.jsonl, traces.jsonl, proposals.jsonl, manifest_*.json}
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

NUM_SHARDS = 2
OUT = "/kaggle/working/outputs/b0_traces"

bootstrap.setup()
codes = bootstrap.run_on_gpus([
    [sys.executable, "-m", "sagate.agent.run_b0", "--out", OUT, "--shard", str(i), "--num-shards", str(NUM_SHARDS)]
    for i in range(NUM_SHARDS)
])
# merge shards (CPU) and extract proposals in the dataset schema
shards = sorted(glob.glob(f"{OUT}/traces_shard*.jsonl"))
with open(f"{OUT}/traces.jsonl", "w") as out:
    for s in shards:
        out.writelines(open(s))
bootstrap.run([sys.executable, "-m", "sagate.agent.extract_proposals", "--traces", f"{OUT}/traces.jsonl",
               "--out", f"{OUT}/proposals.jsonl"])
sys.exit(max(codes))
