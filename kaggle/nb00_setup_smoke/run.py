# NB00 setup + smoke: install, load Qwen3-8B nf4, measure throughput, one gate call, one AgentDojo task.
# Output: /kaggle/working/outputs/nb00/throughput.json (replaces the estimates in ARCHITECTURE.md §9.2).
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

bootstrap.setup()
code = bootstrap.run([sys.executable, "-m", "sagate.smoke", "--out", "/kaggle/working/outputs/nb00"])
sys.exit(code)
