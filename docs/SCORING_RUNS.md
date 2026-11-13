# Scoring runs A–D (final test of B4 and the ablations)

Each run scores **its own two trained models** on dev, attacks and test, on the **same Kaggle account that trained
them** (NB04, model alone, no GateExp rules). The models come straight from your training kernel's output, so no
adapter sharing is needed. The scores do not depend on who runs them: same locked code, same cases, greedy decoding.

| Run | Who | Models scored | Branch | Results folder |
|---|---|---|---|---|
| **A** | Prabhash | `b4_v4_binary_combo`, `b5_v4_no_inter` | `run-a` | `results/data/2026-11-13_eval_run_a/` |
| **B** | Shubham | `b5_v4_no_prov`, `b5_v4_no_auth` | `run-b` | `results/data/2026-11-13_eval_run_b/` |
| **C** | Yogendra | `b5_v4_no_rag`, `b5_v4_no_ask` | `run-c` | `results/data/2026-11-13_eval_run_c/` |
| **D** | Yogendra | `b5_v4_no_esc`, `b5_v4_combo_seed2` | `run-d` | `results/data/2026-11-13_eval_run_d/` |
| V4 | Rinkesh | `b5_v4_combo`, `b5_v4_inferred_prov` | `main` | `results/data/2026-11-13_eval_v4/` |

Time: about 1 hour on 2 × T4 (one model per GPU). Run D: finish training first (`docs/TRAINING_RUNS.md`).

## 1. Get the scoring notebook onto your branch

```bash
git checkout run-a                      # your branch: run-a / run-b / run-c / run-d
git pull origin run-a
git merge origin/main                   # brings the new NB04 (kaggle/nb04_eval_learned) and this guide
```

Only `kaggle/` and `docs/` changed on main since `locked-v4`; `src/`, `configs/`, `resources/`, `annotations/` are
identical, so your models are scored with exactly the code they were trained with.

## 2. Set your run (the only edit)

In `kaggle/nb04_eval_learned/run.py`, set:

```python
GROUP = "A"                             # your run letter
```

Change nothing else.

## 3. Stage and start

```bash
bash kaggle/stage_code.sh --owner <you>
kaggle kernels push -p build/kernels/nb04_eval_learned
kaggle kernels status <you>/sagate-nb04-eval-learned   # QUEUED → RUNNING → COMPLETE
```

**Do not upload a new `sagate-code` version**: the one you trained with (`7435346`) is the one to score with. The
kernel attaches `<you>/sagate-code` and your training kernel `<you>/sagate-nb03-train-qlora` automatically.

In the Kaggle web log, check within the first minutes:

- `sagate code version: 7435346`;
- `adapter <model>: ...` lines for **your two models** (they come from your NB03 output);
- `group A: ['b4_v4_binary_combo', 'b5_v4_no_inter']` (your run).

If it stops with `adapters not attached: [...]`, your NB03 output was not attached or holds other models (for example
a later NB03 version): post the log, do not fix it yourself.

## 4. When it is COMPLETE: results to your branch

```bash
X=a                                                       # your run letter, lower case
mkdir -p /tmp/eval-$X && kaggle kernels output <you>/sagate-nb04-eval-learned -p /tmp/eval-$X
D=results/data/2026-11-13_eval_run_$X && mkdir -p $D
rsync -a --exclude gate_cache /tmp/eval-$X/outputs/predictions/ $D/
cp /tmp/eval-$X/*.log $D/kernel.log 2>/dev/null; cp -r /tmp/eval-$X/logs $D/ 2>/dev/null
ls $D/dev $D/attacks $D/test                              # each: <model>.jsonl, .manifest.json, report.json
git add $D && git commit -m "Result: scoring run ${X^^} and nov13 <time>" && git push origin run-$X
```

Then open (or update) the pull request `run-x` → `main`. Commit only `results/data/2026-11-13_eval_run_x/`
(predictions, reports, logs; a few MB). Never commit `gate_cache/`, adapters or checkpoints.

## Two runs on one account (Yogendra: C and D)

NB04 reads the models from the **latest** output of your training kernel `sagate-nb03-train-qlora`, and each new
NB04 run replaces the previous NB04 output. So keep this order:

1. **Score C first**, while your latest NB03 output still holds the C models: on `run-c`, `GROUP = "C"`, steps 1–4.
   Download and commit the C results (step 4) **before** starting anything else.
2. **Train D** (`docs/TRAINING_RUNS.md`, branch `run-d` from `locked-v4`, NB03 `GROUP = "D"`), and commit its training
   results to `run-d` as usual.
3. **Score D**: on `run-d`, `git merge origin/main`, NB04 `GROUP = "D"`, steps 2–4.

If the D training already ran before C was scored, the C models are no longer in your latest NB03 output. Then attach
the C models from your adapter dataset (training guide step 6): after staging, add `"<you>/sagate-adapters-run-c"` to
`dataset_sources` in `build/kernels/nb04_eval_learned/kernel-metadata.json`, and push. If that dataset does not exist,
post in the chat before doing anything.

## Rules

- Score only from your branch with `main` merged in; the one edit is `GROUP` in NB04.
- Each model's test set is scored once, in this run. Do not re-run it to "improve" a number; if something failed, post
  the log first.
- Do not edit `results/data/RUNS.md`, configs or code. B4's threshold (matched to B5's unsafe rate on dev) and the
  comparison against B5 are done on `main` after all runs are in, from the committed predictions.
