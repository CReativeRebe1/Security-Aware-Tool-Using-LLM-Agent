# Run Guide — Run 1 (B5 standing) and Run 2 (ablations)

Everyone runs from branch `valhalla` at the same commit. Each person uses their **own Kaggle account** (2 × T4,
12 h per session, ~30 GPU-h per week). Read the whole guide once before starting.

## Who runs what

| Run | Person | Job | Kernel | GPU time |
|---|---|---|---|---|
| **1** | Teammate 1 | Train group **A** (B5 + B4) | NB03, `GROUP = "A"` | ~8–10 h |
| **1** | Teammate 2 | Baselines B1–B3 on dev + test | NB02 | ~1–2 h |
| **1** | Teammate 1 | Evaluate B4, B5, `b5_guarded`, `b5_inferred_prov` (after A finishes) | NB04 | ~1.5 h |
| — | Team | **Check B5's standing; decide go / fix** | — | — |
| **2** | Teammate 2 | Train group **B** (−provenance, −authority) | NB03, `GROUP = "B"` | ~8–10 h |
| **2** | Teammate 3 | Train group **C** (−RAG, −intermediate) | NB03, `GROUP = "C"` | ~8–10 h |
| **2** | Teammate 4 | Train group **D** (−ASK, −ESCALATE) | NB03, `GROUP = "D"` | ~6–8 h |
| **2** | Teammate 1 | Evaluate the ablations | NB04 (attach all NB03 kernels) | ~1.5 h |
| **3** | Any | End-to-end B0 vs B5 (+ counterfactual, after calibration) | NB05 | ~5 h |
| **3** | Any | Statistics and report (CPU) | NB06 | < 1 h |

Run 2 starts only after the team agrees on Run 1, so the ablations are compared against the final B5.

## Rules (do not skip)

1. **Same code everywhere.** `git checkout valhalla && git pull`, then `git rev-parse --short HEAD`; post the hash in
   the team chat. Everyone must use the same one.
2. **No design changes based on test numbers.** If a fix is needed after Run 1, design it on train/dev only.
3. **Never attach old outputs** (`sagate-progress-nb03`, earlier NB03 kernels). NB03 skips finished adapters, and
   old adapters were trained on data containing the test set.
4. **Do not edit and commit the `GROUP` line.** Set it in the staged copy (step 2 below).

## Steps for each NB03 / NB02 job

```bash
pip install kaggle==2.2.5                      # once; token in ~/.kaggle/access_token
git checkout valhalla && git pull
bash kaggle/stage_code.sh --owner <your-kaggle-username>
```

1. **Upload the code** (first time `create`, later `version`):
   ```bash
   kaggle datasets create  -p build/sagate-code --dir-mode zip            # first time only
   kaggle datasets version -p build/sagate-code --dir-mode zip -m "$(git rev-parse --short HEAD)"
   ```
   Wait until the dataset shows the new version as ready on Kaggle before pushing a kernel.
2. **NB03 only: set your group** in `build/kernels/nb03_train_qlora/run.py`: `GROUP = "A"` (or B, C, D).
3. **Push** (12 h limit):
   ```bash
   kaggle kernels push -p build/kernels/nb03_train_qlora --accelerator NvidiaTeslaT4 -t 43200
   kaggle kernels push -p build/kernels/nb02_baselines_prompted --accelerator NvidiaTeslaT4 -t 43200
   ```
4. **Check the first lines of the log** (Kaggle → kernel → Logs):
   - `sagate code version: <hash>` must equal the team hash, without `-dirty`.
   - NB03: `group A: [...]`, then `b5_qlora_4way: 2049 examples` and `b4_qlora_binary: 1619 examples`.
   - If the hash is wrong, stop the kernel, wait for the dataset version, push again.
5. **Watch and download:**
   ```bash
   kaggle kernels status <owner>/sagate-nb03-train-qlora
   kaggle kernels output <owner>/sagate-nb03-train-qlora -p runs/run1_nb03_A/
   ```
   If a session times out, push again with that kernel's output attached as `sagate-progress-nb03`: training
   resumes from the last checkpoint (every 100 steps). This is the only case where attaching old output is allowed.

## NB04 (evaluation)

1. Every NB03 kernel you need must be **shared** with the account running NB04 (Kaggle → kernel → Share).
2. In `build/kernels/nb04_eval_learned/kernel-metadata.json`, set `kernel_sources` to all NB03 kernels, e.g.
   `["<owner1>/sagate-nb03-train-qlora", "<owner2>/sagate-nb03-train-qlora"]`.
3. Push as above. In the log, check one `adapter <name>: ... (trained <date>, code <hash>)` line per condition:
   the date must be from this run and the hash the team hash. Run 1 prints `ablations with adapters: none`; that is
   expected.

## What to record

Fill one row per kernel in the run sheet below (copy it into `docs/JOURNAL.md` after each run).

| Date | Person | Kernel | Group | Code hash (from log) | Config hash (manifest) | Status | GPU h | Notes |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

Keep these files from every run in `results/data/run<N>/` and commit them (they are small):

| From | Keep |
|---|---|
| NB03 | `adapters/<condition>/train_summary.json`, `adapters/<condition>/manifest.json`, the kernel log |
| NB02 / NB04 | `predictions/{dev,test}/*.jsonl`, `*.manifest.json`, `report.json`, `dev/b4_threshold.json`, the kernel log |
| NB05 | `e2e/<condition>/traces.jsonl`, `report/e2e.json`, the kernel log |

Do **not** commit adapters (167 MB each); they stay as Kaggle kernel outputs.

## What to look at after Run 1

From `predictions/test/report.json` (NB04):

| Metric | Where | Target |
|---|---|---|
| Unauthorized-action rate | `b5_qlora_4way`, `b5_guarded` | ≤ 5% |
| Unnecessary deferral | same | ≤ 10% |
| Final-resolution success | same; B4 vs `b5_qlora_4way@b4_cases` for H2 | higher than B4 |
| Executed without confirmation | same | low |
| Inferred vs oracle provenance | `b5_inferred_prov` vs `b5_qlora_4way` | report the gap |

Expected (estimates, not measured): B5 + guards 88–94% correct, 6–10% unsafe; B5 alone 12–20% unsafe.

## Training settings (same for every condition)

QLoRA on `unsloth/Qwen3-8B-bnb-4bit`, LoRA r = 16, α = 32, dropout 0.05 on all projections, batch 1 × 16 accumulation,
lr 2e-4 cosine, **2 epochs**, max length 2,560 tokens (longest example ~1,950, so none are dropped), seed 42.
Training data: 1,000 generated variants + 1,049 human-labelled cases. Do not change these between conditions or
after seeing test results.
