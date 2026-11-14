# NB04 final scoring, every learned model ALONE (no GateExp rules; the facts it was trained with are shown):
# B4, B5 (b5_v4_combo), its second seed, the six ablations and the inferred-provenance swap on dev, attacks and test.
# Split by GROUP so each run scores its own models on its own account (docs/SCORING_RUNS.md); the scores do not
# depend on where they run (same locked code, same cases, greedy decoding).
# B4's threshold is matched to B5's unauthorized-action rate on dev (CPU, dev only), then applied to attacks / test:
# here when B4 and B5 are scored together (GROUP "ALL"), otherwise afterwards from the committed predictions.
# Adapters: attach the NB03 output / adapter dataset of the run (any folder with adapter_config.json).
# Output: /kaggle/working/outputs/predictions/{dev,attacks,test}/ + report.json (+ b4_threshold.json with "ALL")
import glob
import os
import sys

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

OUT = "/kaggle/working/outputs"
LIMIT = None            # e.g. 50 for a quick dry run
B4, B5 = "b4_v4_binary_combo", "b5_v4_combo"
INFERRED = "b5_v4_inferred_prov"                 # test-time swap: uses the B5 adapter, never trained under this name
GROUPS = {"V4": [B5, INFERRED],                  # Rinkesh: the final B5 + inferred provenance
          "A": [B4, "b5_v4_no_inter"],
          "B": ["b5_v4_no_prov", "b5_v4_no_auth"],
          "C": ["b5_v4_no_rag", "b5_v4_no_ask"],
          "D": ["b5_v4_no_esc", "b5_v4_combo_seed2"]}
GROUPS["ALL"] = [m for g in ("V4", "A", "B", "C", "D") for m in GROUPS[g]]
GROUP = "V4"                    # V4 | A | B | C | D | ALL (docs/SCORING_RUNS.md); the only edit per run

root = bootstrap.setup()
py = sys.executable
adapters = bootstrap.collect_adapters()        # every attached NB03 output / adapter dataset; newest copy of each
models = GROUPS[GROUP]
need = sorted({B5 if m == INFERRED else m for m in models})
missing = [c for c in need if not adapters or not os.path.exists(f"{adapters}/{c}")]
if missing:
    sys.exit(f"adapters not attached: {missing}")
print(f"group {GROUP}: {models}", flush=True)
cases = {"dev": os.path.join(root, "annotations", "dev_cases.jsonl"),
         "attacks": os.path.join(root, "annotations", "attack_cases.jsonl"),     # no split tag: scored as "test"
         "test": os.path.join(root, "annotations", "test_cases.jsonl")}
limit = f" --limit {LIMIT}" if LIMIT else ""


def run(cond, pool, responses="clean", cite=False):
    split = "dev" if pool == "dev" else "test"
    return (f"{py} -m sagate.eval.run_gate --condition {cond} --cases {cases[pool]} --pool {split} "
            f"--responses {responses} --adapter-dir {adapters} --out {OUT}/predictions/{pool}"
            f"{' --cite' if cite else ''}{limit}")


def jobs(m):
    """The same jobs for a model whichever group scores it."""
    if m == B5:
        return [run(B5, "dev"), run(B5, "attacks"), run(B5, "test", cite=True), run(B5, "test", "noisy")]
    if m == INFERRED:
        return [run(m, "dev"), run(m, "test"), run(m, "test", "noisy")]
    return [run(m, "dev"), run(m, "attacks"), run(m, "test")]


# two GPUs: models alternate between them; test is scored once per model, here
gpus = [[], []]
for i, m in enumerate(models):
    gpus[i % 2] += jobs(m)
codes = bootstrap.run_on_gpus([["bash", "-c", " ; ".join(g)] for g in gpus if g])

d = f"{OUT}/predictions/dev"
if B4 in models and B5 in models:
    bootstrap.run([py, "-m", "sagate.eval.pareto", "select", "--b4", f"{d}/{B4}.jsonl", "--b5", f"{d}/{B5}.jsonl",
                   "--cases", cases["dev"], "--out", f"{d}/b4_threshold.json"])
    for pool in ("attacks", "test"):
        p = f"{OUT}/predictions/{pool}"
        bootstrap.run([py, "-m", "sagate.eval.pareto", "apply", "--pred", f"{p}/{B4}.jsonl",
                       "--threshold-file", f"{d}/b4_threshold.json", "--out", f"{p}/{B4}_matched.jsonl"])
for pool in cases:
    preds = sorted(glob.glob(f"{OUT}/predictions/{pool}/*.jsonl"))
    if preds:
        bootstrap.run([py, "-m", "sagate.eval.report", "--cases", cases[pool], "--pred", *preds,
                       "--json", f"{OUT}/predictions/{pool}/report.json"])
sys.exit(max(codes))
