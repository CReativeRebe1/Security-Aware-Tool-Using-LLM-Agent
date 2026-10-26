# NB01 B0 traces: Qwen3-8B agent (no gate) over the strict test scenarios (POOLS), sharded over 2 GPUs.
# Output: /kaggle/working/outputs/b0_traces/{traces_shard*.jsonl, traces.jsonl, b0_summary.json, proposals.jsonl,
#         manifest_*.json}
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

NUM_SHARDS = 2
POOLS = "test"          # 142 test scenarios (B0 utility/ASR); "train,test" adds the 276 train-source scenarios
OUT = "/kaggle/working/outputs/b0_traces"

bootstrap.setup()
codes = bootstrap.run_on_gpus([
    [sys.executable, "-m", "sagate.agent.run_b0", "--out", OUT, "--pools", POOLS, "--shard", str(i),
     "--num-shards", str(NUM_SHARDS)]
    for i in range(NUM_SHARDS)
])
# merge shards (CPU; one row per trace, retried crashes deduplicated) + B0 utility/ASR summary, then extract
# proposals in the dataset schema
shards = sorted(glob.glob(f"{OUT}/traces_shard*.jsonl"))
bootstrap.run([sys.executable, "-m", "sagate.agent.run_b0", "--merge", *shards, "--out", OUT])
bootstrap.run([sys.executable, "-m", "sagate.agent.extract_proposals", "--traces", f"{OUT}/traces.jsonl",
               "--out", f"{OUT}/proposals.jsonl"])
sys.exit(max(codes))
