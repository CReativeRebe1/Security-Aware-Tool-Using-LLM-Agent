# NB05 end-to-end: the Qwen3 agent with the B5 gate (GatedToolsExecutor) over the 142 strict test scenarios, sharded
# over 2 GPUs; B0 is NB01 (same agent, same scenarios). EXTRA conditions (e.g. "b3_prompt_4way") run after B5 if
# time allows. Then end-to-end metrics for B0 and every gated condition.
# Output: /kaggle/working/outputs/e2e/<condition>/{traces*.jsonl, b0_summary.json}, outputs/report/e2e.json
import glob
import os
import shutil
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

CONDITIONS = ["b5_qlora_4way"]
EXTRA = []              # e.g. ["b3_prompt_4way"] if the session has time (proposal §7: B3 if time permits)
NUM_SHARDS = 2
LIMIT = None
OUT = "/kaggle/working/outputs"

root = bootstrap.setup()
py = sys.executable
adapters = bootstrap.collect_adapters()        # every attached NB03 kernel; newest copy of each condition
if adapters is None and any(c.startswith(("b4", "b5")) for c in CONDITIONS + EXTRA):
    sys.exit("NB03 adapters not attached")
limit = ["--limit", str(LIMIT)] if LIMIT else []
codes = []
for cond in CONDITIONS + EXTRA:
    out = f"{OUT}/e2e/{cond}"
    os.makedirs(out, exist_ok=True)
    # resume from an earlier run attached as "sagate-progress-nb05"
    for prev in glob.glob(f"/kaggle/input/**/sagate-progress-nb05/**/e2e/{cond}/traces_shard*.jsonl", recursive=True):
        print("resuming from", prev, flush=True)
        shutil.copy(prev, out)
    codes += bootstrap.run_on_gpus([
        [py, "-m", "sagate.agent.run_e2e", "--condition", cond, "--out", out, "--shard", str(i),
         "--num-shards", str(NUM_SHARDS), *(["--adapter-dir", adapters] if adapters else []), *limit]
        for i in range(NUM_SHARDS)
    ])
    bootstrap.run([py, "-m", "sagate.agent.run_e2e", "--condition", cond, "--out", out, "--merge",
                   *sorted(glob.glob(f"{out}/traces_shard*.jsonl"))])

b0 = sorted(glob.glob("/kaggle/input/**/b0_traces/traces.jsonl", recursive=True), key=len)
traces = b0[:1] + [f"{OUT}/e2e/{c}/traces.jsonl" for c in CONDITIONS + EXTRA if os.path.exists(f"{OUT}/e2e/{c}/traces.jsonl")]
bootstrap.run([py, "-m", "sagate.eval.e2e_metrics", "--traces", *traces, "--json", f"{OUT}/report/e2e.json"])
sys.exit(max(codes or [0]))
