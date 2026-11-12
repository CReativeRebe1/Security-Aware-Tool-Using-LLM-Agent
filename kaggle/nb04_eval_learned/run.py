# NB04 final scoring, every learned model ALONE (no GateExp rules; the facts it was trained with are shown):
# B4, B5 (b5_v4_combo), its second seed, the six ablations and the inferred-provenance swap on dev, attacks and test.
# B4's threshold is matched to B5's unauthorized-action rate on dev (CPU, dev only), then applied to attacks / test.
# Adapters: attach the NB03 outputs / adapter datasets of runs V4, A, B, C, D (any folder with adapter_config.json).
# Output: /kaggle/working/outputs/predictions/{dev,attacks,test}/ + b4_threshold.json + report.json
import glob
import os
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

OUT = "/kaggle/working/outputs"
LIMIT = None            # e.g. 50 for a quick dry run


root = bootstrap.setup()
py = sys.executable
adapters = bootstrap.collect_adapters()        # every attached NB03 output / adapter dataset; newest copy of each
B4, B5 = "b4_v4_binary_combo", "b5_v4_combo"
OTHERS = ["b5_v4_combo_seed2", "b5_v4_no_prov", "b5_v4_no_auth", "b5_v4_no_inter", "b5_v4_no_rag",
          "b5_v4_no_ask", "b5_v4_no_esc"]
need = [B4, B5, *OTHERS]
missing = [c for c in need if not adapters or not os.path.exists(f"{adapters}/{c}")]
if missing:
    sys.exit(f"adapters not attached: {missing}")
cases = {"dev": os.path.join(root, "annotations", "dev_cases.jsonl"),
         "attacks": os.path.join(root, "annotations", "attack_cases.jsonl"),     # no split tag: scored as "test"
         "test": os.path.join(root, "annotations", "test_cases.jsonl")}
limit = f" --limit {LIMIT}" if LIMIT else ""


def run(cond, pool, responses="clean", cite=False):
    split = "dev" if pool == "dev" else "test"
    return (f"{py} -m sagate.eval.run_gate --condition {cond} --cases {cases[pool]} --pool {split} "
            f"--responses {responses} --adapter-dir {adapters} --out {OUT}/predictions/{pool}"
            f"{' --cite' if cite else ''}{limit}")


# two GPUs, about the same number of case-runs each; test is scored once, here
gpu0 = [run(B5, "dev"), run(B4, "dev"), run(B5, "attacks"), run(B4, "attacks"),
        run(B5, "test", cite=True), run(B5, "test", "noisy"), run(B4, "test"),
        run("b5_v4_inferred_prov", "dev"), run("b5_v4_inferred_prov", "test"),
        run("b5_v4_inferred_prov", "test", "noisy")]
for c in OTHERS[:2]:
    gpu0 += [run(c, "dev"), run(c, "attacks"), run(c, "test")]
gpu1 = []
for c in OTHERS[2:]:
    gpu1 += [run(c, "dev"), run(c, "attacks"), run(c, "test")]
codes = bootstrap.run_on_gpus([["bash", "-c", " ; ".join(gpu0)], ["bash", "-c", " ; ".join(gpu1)]])

d = f"{OUT}/predictions/dev"
bootstrap.run([py, "-m", "sagate.eval.pareto", "select", "--b4", f"{d}/{B4}.jsonl", "--b5", f"{d}/{B5}.jsonl",
               "--cases", cases["dev"], "--out", f"{d}/b4_threshold.json"])
for pool in ("attacks", "test"):
    p = f"{OUT}/predictions/{pool}"
    bootstrap.run([py, "-m", "sagate.eval.pareto", "apply", "--pred", f"{p}/{B4}.jsonl",
                   "--threshold-file", f"{d}/b4_threshold.json", "--out", f"{p}/{B4}_matched.jsonl"])
for pool in cases:
    preds = sorted(glob.glob(f"{OUT}/predictions/{pool}/*.jsonl"))
    bootstrap.run([py, "-m", "sagate.eval.report", "--cases", cases[pool], "--pred", *preds,
                   "--json", f"{OUT}/predictions/{pool}/report.json"])
sys.exit(max(codes))
