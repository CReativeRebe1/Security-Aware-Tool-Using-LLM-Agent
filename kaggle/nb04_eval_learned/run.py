# NB04 learned gates: B4 (unthresholded, p_allow) and B5 on dev -> B4 threshold matched to B5's dev unauthorized-action
# rate (CPU, dev only) -> B4 at that threshold on test; B5, the evidence/decision-space ablations and the
# inferred-provenance swap on test (B5 also with noisy replies and evidence_cited). Two GPU jobs (one per GPU).
# Cases: annotations/test_cases.jsonl (frozen gold) and NB03's generated dev pool (outputs/sft/dev_cases.jsonl).
# Output: /kaggle/working/outputs/predictions/{dev,test}/ + b4_threshold.json + report.json
import glob
import os
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

OUT = "/kaggle/working/outputs"
LIMIT = None            # e.g. 50 for a quick dry run


def find(pattern):
    hits = sorted(glob.glob(f"/kaggle/input/**/{pattern}", recursive=True), key=len)
    return hits[0] if hits else None


root = bootstrap.setup()
py = sys.executable
adapters = bootstrap.collect_adapters()        # every attached NB03 kernel; newest copy of each condition
if not adapters or not os.path.exists(f"{adapters}/b5_qlora_4way"):
    sys.exit("NB03 adapters not attached (no adapters/b5_qlora_4way under /kaggle/input)")
test = os.path.join(root, "annotations", "test_cases.jsonl")
if not os.path.exists(test):
    print("annotations/test_cases.jsonl not staged: dry run on the unlabelled test candidates", flush=True)
    test = f"{OUT}/cases/test_candidates.jsonl"
    bootstrap.run([py, "-m", "sagate.data.build_cases", "--pool", "test", "--out", test])
dev = find("sft/dev_cases.jsonl")
if dev is None:
    dev = f"{OUT}/cases/dev_cases.jsonl"
    bootstrap.run([py, "-m", "sagate.train.variants", "--pool", "dev", "--out", dev])
cases = {"test": test, "dev": dev}
limit = f" --limit {LIMIT}" if LIMIT else ""


def run(cond, pool, responses="clean", cite=False):
    return (f"{py} -m sagate.eval.run_gate --condition {cond} --cases {cases[pool]} --pool {pool} "
            f"--responses {responses} --adapter-dir {adapters} --out {OUT}/predictions/{pool}"
            f"{' --cite' if cite else ''}{limit}")


gpu0 = [run("b4_qlora_binary", "dev"), run("b5_qlora_4way", "dev"), run("b4_qlora_binary", "test"),
        run("b5_qlora_4way", "test", cite=True), run("b5_qlora_4way", "test", "noisy"),
        run("b5_inferred_prov", "test"), run("b5_inferred_prov", "test", "noisy")]
gpu1 = [run(c, "test") for c in ("b5_no_prov", "b5_no_auth", "b5_no_rag", "b5_no_ask", "b5_no_esc", "b5_no_inter")]
codes = bootstrap.run_on_gpus([["bash", "-c", " ; ".join(gpu0)], ["bash", "-c", " ; ".join(gpu1)]])

d, t = f"{OUT}/predictions/dev", f"{OUT}/predictions/test"
bootstrap.run([py, "-m", "sagate.eval.pareto", "select", "--b4", f"{d}/b4_qlora_binary.jsonl",
               "--b5", f"{d}/b5_qlora_4way.jsonl", "--cases", cases["dev"], "--out", f"{d}/b4_threshold.json"])
bootstrap.run([py, "-m", "sagate.eval.pareto", "apply", "--pred", f"{t}/b4_qlora_binary.jsonl",
               "--threshold-file", f"{d}/b4_threshold.json", "--out", f"{t}/b4_qlora_binary_matched.jsonl"])
for pool in ("dev", "test"):
    preds = sorted(glob.glob(f"{OUT}/predictions/{pool}/*.jsonl"))
    bootstrap.run([py, "-m", "sagate.eval.report", "--cases", cases[pool], "--pred", *preds,
                   "--json", f"{OUT}/predictions/{pool}/report.json"])
sys.exit(max(codes))
