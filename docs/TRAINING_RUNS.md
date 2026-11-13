# Training runs A–D

Four independent Kaggle runs. Each trains two models at once on one **2 × T4** machine (one model per GPU) from the
locked code `locked-v4`. All models use the same data and recipe as the final B5 (`b5_v4_combo`: human +
augmented + combo data, cost matrix, decision smoothing, group weights, 1 epoch); each differs from it only in the
part named below.

| Run | GPU 0 | GPU 1 | Time | Branch |
|---|---|---|---|---|
| **A** | `b4_v4_binary_combo` (B4, binary) | `b5_v4_no_inter` (H3) | ~5 h | `run-a` |
| **B** | `b5_v4_no_prov` (H1) | `b5_v4_no_auth` (H1) | ~5 h | `run-b` |
| **C** | `b5_v4_no_rag` | `b5_v4_no_ask` | ~5 h | `run-c` |
| **D** | `b5_v4_no_esc` | `b5_v4_combo_seed2` (B5, seed 7: seed variance) | ~5 h | `run-d` |

Times: ~6.3 s per training example on one T4; 2,698 examples (B4 / no_ask / no_esc have fewer, see below).
Each run needs about **6 free GPU hours** on your Kaggle account (kaggle.com → Settings → quota).

## 0. Once per machine

```bash
pip install kaggle                       # Kaggle CLI
# kaggle.com → Settings → API → "Create New Token" → save kaggle.json to ~/.kaggle/kaggle.json, then:
chmod 600 ~/.kaggle/kaggle.json
kaggle datasets list -m                  # works = you are logged in
```

Your Kaggle username is `<you>` below.

## 1. Branch

```bash
git checkout main && git pull
git checkout locked-v4 -b run-a          # your run letter: run-a / run-b / run-c / run-d
```

## 2. Set your run (the only edit)

In `kaggle/nb03_train_qlora/run.py`, set:

```python
GROUP = "A"                              # your run letter
```

Change nothing else. This file is the Kaggle notebook, not part of the code package, so the code everyone trains
with stays identical.

## 3. Stage and upload the code

```bash
bash kaggle/stage_code.sh --owner <you>
cat build/sagate-code/GIT_SHA            # must print the locked-v4 commit (no "-dirty")
kaggle datasets create  -p build/sagate-code    # first time on your account
kaggle datasets version -p build/sagate-code -m "locked-v4"   # if <you>/sagate-code already exists
kaggle datasets status <you>/sagate-code        # wait until: ready
```

`-dirty` means you changed something under `src/`, `configs/` or `resources/`: undo it (`git status`).

## 4. Start the training

```bash
kaggle kernels push -p build/kernels/nb03_train_qlora
kaggle kernels status <you>/sagate-nb03-train-qlora   # QUEUED → RUNNING → COMPLETE
```

The kernel is set to 2 × T4 with internet on. In the Kaggle web log, check within the first minutes:

- `GIT_SHA` = the locked-v4 commit (if not, the old code dataset was attached: stop the run, wait for `ready`, push again);
- `group A: ['b4_v4_binary_combo', 'b5_v4_no_inter']` (your run);
- one `examples -> ... targets {...}` line per model. Expected:

| Model | Examples | Targets |
|---|---|---|
| `b4_v4_binary_combo` | 1,904 | ALLOW 689, BLOCK 1,215 |
| `b5_v4_no_inter`, `no_prov`, `no_auth`, `no_rag`, `combo_seed2` | 2,698 | ALLOW 944, ASK_USER 603, BLOCK 749, ESCALATE 402 |
| `b5_v4_no_ask` | 1,952 | ALLOW 725, BLOCK 927, ESCALATE 300 |
| `b5_v4_no_esc` | 2,650 | ALLOW 908, ASK_USER 603, BLOCK 1,139 |

(B4 never asks, so it has no second-round examples; `no_ask` / `no_esc` keep the second rounds of the decisions they
still have. A removed ASK / ESCALATE is trained as BLOCK.)

If the session stops early, push the same kernel again: finished models are skipped and the rest resume from their
last checkpoint (attach your previous output as `sagate-progress-nb03`, see `docs/RUN_GUIDE.md`).

## 5. When it is COMPLETE: results to git

```bash
mkdir -p /tmp/run-a && kaggle kernels output <you>/sagate-nb03-train-qlora -p /tmp/run-a
D=results/data/2026-11-13_train_run_a && mkdir -p $D
for c in /tmp/run-a/adapters/*/; do n=$(basename $c); cp $c/train_summary.json $D/$n.train_summary.json; done
cp /tmp/run-a/*.log $D/kernel.log 2>/dev/null; cp -r /tmp/run-a/logs $D/ 2>/dev/null
git add $D && git commit -m "Result: training run A and nov13 <time>" && git push -u origin run-a
```

Only the small files go to git (summaries, logs). **Never commit `adapters/` or `checkpoints/`** (hundreds of MB).
Do not edit `results/data/RUNS.md`, configs or code on your branch; Rinkesh adds the RUNS.md rows when merging.
Then open a pull request `run-a` → `main` on GitHub.

## 6. Share the trained models (Kaggle, not git)

```bash
mkdir -p /tmp/adapters-run-a && cp -r /tmp/run-a/adapters/* /tmp/adapters-run-a/
cat > /tmp/adapters-run-a/dataset-metadata.json <<EOF
{"title": "sagate-adapters-run-a", "id": "<you>/sagate-adapters-run-a", "licenses": [{"name": "other"}]}
EOF
kaggle datasets create -p /tmp/adapters-run-a --dir-mode zip
```

On the dataset's Kaggle page: Settings → Sharing → add **satorugojo13** as collaborator (viewer is enough). Post the
dataset id in the team chat. This is the backup copy of the models; scoring (`docs/SCORING_RUNS.md`) reads them from
your NB03 output, so no sharing is needed for it.

## Rules

- Train only from `locked-v4`; the one edit is `GROUP`.
- Scoring (dev, attacks, test) follows `docs/SCORING_RUNS.md`: each model's test set is scored once, there.
- If something looks different from the table in step 4, stop and post the log; do not fix it on your branch.
