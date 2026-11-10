# Kaggle Guide — running the project without the usual pitfalls

Every command here was run on 2026-11-10 against a fresh Kaggle account. Follow it top to bottom the first time.
Who runs which job, and what to record, is in `docs/RUN_GUIDE.md`.

## 1. One-time setup (≈ 15 min)

1. **Kaggle account:** Settings → **Phone verification**. Without it, GPUs and internet are unavailable.
2. **API token:** Settings → API → **Create New Token**. Save it on your machine (do not paste it anywhere else):
   ```bash
   mkdir -p ~/.kaggle
   nano ~/.kaggle/access_token        # paste the token; save with Ctrl+O then Enter, exit with Ctrl+X
   chmod 600 ~/.kaggle/access_token
   ```
   (If you downloaded `kaggle.json` instead, put it at `~/.kaggle/kaggle.json` and `chmod 600` it.)
3. **Kaggle CLI:**
   ```bash
   pip install --user kaggle==2.2.5 six     # 'six' is a missing dependency of 2.2.5
   kaggle config view                        # must show YOUR username
   ```
4. **Code:**
   ```bash
   git clone -b valhalla git@github.com:CReativeRebe1/Security-Aware-Tool-Using-LLM-Agent.git
   cd Security-Aware-Tool-Using-LLM-Agent
   git rev-parse --short HEAD               # compare with the team hash
   ```

## 2. Upload the code (every time the code changes)

```bash
bash kaggle/stage_code.sh --owner <your-kaggle-username>
kaggle datasets create  -p build/sagate-code --dir-mode zip        # first time only
kaggle datasets version -p build/sagate-code --dir-mode zip -m "$(git rev-parse --short HEAD)"   # later times
```

**Check that Kaggle serves the new version** (do not trust "ready"):
```bash
kaggle datasets download <your-username>/sagate-code -f GIT_SHA -p /tmp/sha && cat /tmp/sha/GIT_SHA
```
It must print the hash from step 1.4. If not, wait a minute and repeat.

## 3. Smoke test (once per code version, ≈ 20 min)

```bash
kaggle kernels push -p build/kernels/nb07_smoke_all --accelerator NvidiaTeslaT4 -t 10800
kaggle kernels status <your-username>/sagate-nb07-smoke-all       # repeat until COMPLETE
kaggle kernels output <your-username>/sagate-nb07-smoke-all -p runs/smoke/
cat runs/smoke/outputs/smoke_summary.json
```
Every step must show `"ok": true`. If one fails, send the matching log from `runs/smoke/logs/<step>/` to the team
before running anything else.

## 4. Real jobs

| Job | Before pushing | Push |
|---|---|---|
| Training (NB03) | In `build/kernels/nb03_train_qlora/run.py` set `GROUP = "A"` (or B, C, D as assigned) | `kaggle kernels push -p build/kernels/nb03_train_qlora --accelerator NvidiaTeslaT4 -t 43200` |
| Baselines (NB02) | nothing | `kaggle kernels push -p build/kernels/nb02_baselines_prompted --accelerator NvidiaTeslaT4 -t 43200` |
| Evaluation (NB04) | Share every NB03 kernel with this account; list them in `kernel_sources` of `build/kernels/nb04_eval_learned/kernel-metadata.json` | `kaggle kernels push -p build/kernels/nb04_eval_learned --accelerator NvidiaTeslaT4 -t 43200` |

Then check the first lines of the log (Kaggle → your kernel → Logs):
- `sagate code version: <hash>`: the team hash, without `-dirty`.
- NB03: `group A: [...]`, and example counts (B5 about 2,050, B4 about 1,620).
- NB04: one `adapter <name>: ... (trained <date>, code <hash>)` line per trained condition.

Download when done: `kaggle kernels output <your-username>/<kernel> -p runs/<run>_<job>/`

## 5. Caveats we hit (read these)

| Problem | What to do |
|---|---|
| Kaggle says the dataset is "ready" but still serves the old code | Always check `GIT_SHA` (section 2); a stale upload once wasted a full training session |
| No `--accelerator NvidiaTeslaT4` | You may get one P100 or no GPU; always pass it |
| Session limit is 12 h | Push with `-t 43200`. If a run stops early, push again with its output attached as `sagate-progress-nb03`: training resumes from the last checkpoint (every 100 steps) |
| Attaching old outputs | Never, except for the resume above. NB03 skips "finished" adapters, and old adapters were trained on data that contained the test set |
| Out of GPU memory on long examples | Fixed in the code (T4 attention fix, max length 3,072). The smoke test trains on the longest examples to prove it |
| T4 has no bfloat16 | The code forces float16; do not change `compute_dtype` |
| Weekly GPU quota (~30 h) | Check Settings → Quota before a 10 h job; one training group uses most of a week |
| Kernels in another account | They must be **shared** with you before NB04 can attach them |
| `GROUP` edited in `kaggle/nb03_train_qlora/run.py` | Edit only the staged copy in `build/`; never commit it |
| Log says "Could not find cuda drivers" | Harmless: it comes from TensorFlow, not from our PyTorch code |
| Kaggle unpacks the code archive itself | Handled by `bootstrap.py`; nothing to do |
| `build/` folder | Recreated by `stage_code.sh`; ignored by git |

## 6. Expected times (2 × T4)

| Job | Time |
|---|---|
| Smoke test (NB07) | ~20 min |
| Training one group (NB03, 2 epochs) | to be filled from the smoke test with the T4 fix |
| Baselines (NB02) | ~1–2 h |
| Evaluation (NB04) | ~1.5 h |
| End-to-end (NB05) | ~5 h |
