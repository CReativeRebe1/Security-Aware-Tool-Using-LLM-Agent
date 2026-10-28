# NB06 statistics + report (CPU): metrics with raw counts, H1/H2/H3 paired tests (bootstrap CI + exact McNemar),
# Holm-Bonferroni over the secondary family, clean vs noisy, error categories, the Pareto frontier and the qualitative
# example picker, over NB02 (B1-B3) and NB04 (B4, B5, ablations) test predictions and NB05's end-to-end metrics.
# Output: /kaggle/working/outputs/report/{report.md, report.json, pareto.png, pareto_test.json}
import glob
import os
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

OUT = "/kaggle/working/outputs/report"

root = bootstrap.setup("dev")
py = sys.executable
cases = os.path.join(root, "annotations", "test_cases.jsonl")
if not os.path.exists(cases):
    sys.exit("annotations/test_cases.jsonl not staged: NB06 needs the frozen gold test set")
preds = {}
for p in sorted(glob.glob("/kaggle/input/**/predictions/test/*.jsonl", recursive=True)):
    preds.setdefault(os.path.basename(p), p)          # one file per condition name (NB02 and NB04 do not overlap)
preds = sorted(preds.values())
print("predictions:", [os.path.basename(p) for p in preds], flush=True)
e2e = sorted(glob.glob("/kaggle/input/**/report/e2e.json", recursive=True), key=len)
os.makedirs(OUT, exist_ok=True)
bootstrap.run([py, "-m", "pip", "install", "-q", "matplotlib"])
code = bootstrap.run([py, "-m", "sagate.eval.analysis", "--cases", cases, "--pred", *preds, "--out", OUT,
                      *(["--e2e", e2e[0]] if e2e else [])])
b4 = [p for p in preds if os.path.basename(p) == "b4_qlora_binary.jsonl"]
points = [p for p in preds if "_noisy" not in os.path.basename(p)]
bootstrap.run([py, "-m", "sagate.eval.pareto", "curve", "--b4", *b4, "--cases", cases, "--points", *points,
               "--out", f"{OUT}/pareto_test.json", "--png", f"{OUT}/pareto_test.png"])
sys.exit(code)
