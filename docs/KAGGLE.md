# How to run on Kaggle

Every GPU stage of the project runs from one notebook, [`notebooks/kaggle_pipeline.ipynb`](../notebooks/kaggle_pipeline.ipynb).
You upload the code once as a private Kaggle dataset, attach it to the notebook, pick the stages to run, and start
a background run. Every stage resumes where it stopped, so a long job can be split across several sessions.

| Stage | Does | Output (`/kaggle/working/outputs/…`) | Needs |
|---|---|---|---|
| `smoke` | loads the model, measures speed, makes one gate decision, runs one AgentDojo task | `smoke/throughput.json` | — |
| `b0_traces` | Qwen3-8B agent with no gate over the test scenarios, then the train scenarios | `b0/traces.jsonl`, `b0/proposals.jsonl` | — |
| `cases` | builds gate cases for the test and dev pools (dataset logs + B0 proposals if present) | `cases/{test,dev}_candidates.jsonl` | `b0` optional |
| `baselines` | B1 rules, B2 prompted binary, B3 prompted four-way, B3 with noisy user replies, report | `predictions/{test,dev}/*.jsonl`, `report.json` | `cases` |

---

## 1. One-time setup

1. **Kaggle account with phone verification.** Without it, GPUs and internet access are disabled
   (*Settings → Phone verification*).
2. **Kaggle CLI** on your machine:
   ```bash
   pip install kaggle
   ```
   Create an API token (*Kaggle → Settings → API → Create New Token*) and put the downloaded `kaggle.json` in
   `C:\Users\<you>\.kaggle\kaggle.json` on Windows or `~/.kaggle/kaggle.json` on Linux/macOS.
3. **Upload the code** from the repository root, replacing `<kaggle-user>` with your Kaggle username:
   ```bash
   python scripts/stage_kaggle_code.py --owner <kaggle-user>
   kaggle datasets create -p build/kaggle-code --dir-mode zip
   ```
   This creates the private dataset `<kaggle-user>/secgate-code`, about 30 MB. It holds the code, configs,
   policy resources and the AgentDojo data.

## 2. After every code change

```bash
python scripts/stage_kaggle_code.py --owner <kaggle-user>
kaggle datasets version -p build/kaggle-code --dir-mode zip -m "short description"
```

Wait until the new version shows as ready on the dataset page before you start a run, or the notebook will mount
the previous version. The notebook prints `code version: <git sha>` first, so you can check which version ran.

## 3. Create the notebook (once)

1. *Kaggle → Code → New Notebook → File → Import Notebook*, then upload `notebooks/kaggle_pipeline.ipynb`.
2. In the right-hand panel:
   - **Session options → Accelerator:** `GPU T4 x2`
   - **Session options → Internet:** on (needed for `pip install` and the model download)
   - **Input → Add Input → Datasets → Your Datasets:** add `secgate-code`
3. Optional: to pull the code from GitHub instead of the dataset, add a secret named `GITHUB_TOKEN`
   (*Add-ons → Secrets*) with read access to the repository. Then set `CODE_SOURCE = "github"` and
   `GIT_REF = "<branch>"` in the parameters cell.

## 4. Choose what to run (parameters cell)

```python
STAGES = ["smoke", "b0_traces", "cases", "baselines"]   # any subset; always runs in this order
SMOKE = True                     # True = tiny slices + Qwen3-0.6B, finishes in minutes
CODE_SOURCE = "dataset"          # or "github"
MODEL_ID = None                  # None = unsloth/Qwen3-8B-bnb-4bit from configs/base.yaml
B0_POOLS = "test,train"          # "test" alone if time is short (test is what the end-to-end numbers need)
CASE_POOLS = ["test", "dev"]
PROMPTED = ["b2_prompt_binary", "b3_prompt_4way"]
```

## 5. Run

Use **Save Version → Save & Run All (Commit)**, not the interactive editor. A committed run keeps going after
you close the browser, and its `/kaggle/working` folder is saved as the version's output. Interactive output
is lost when the session ends.

Recommended order:

| Run | Parameters | Purpose | Rough time |
|---|---|---|---|
| 1 | all four stages, `SMOKE = True` | checks the whole chain end to end | ~15–30 min |
| 2 | `["smoke", "b0_traces"]`, `SMOKE = False` | real throughput numbers and the Qwen3-8B B0 traces | several hours; check `smoke/throughput.json` after the first minutes |
| 3 | `["cases", "baselines"]`, `SMOKE = False`, run 2's output attached (step 6) | gate cases with B0 proposals, then B1/B2/B3 | ~2–4 h |

Kaggle stops a session after 12 hours. If a run is cut off, attach its output and run the same stages again
(step 6); finished work is skipped.

## 6. Continue from an earlier run

To give a run the outputs of an earlier one (B0 traces for `cases`, or a run that timed out):

1. Open the notebook, then *Add Input → Your Work → Notebooks*, and pick this notebook (the version you need).
2. Run again. Any file under `/kaggle/input/*/outputs/` is found automatically:
   - `b0_traces` copies the earlier trace shards and only runs the scenarios that are still missing;
   - `cases` uses the earlier `b0/proposals.jsonl` and `b0/traces.jsonl`;
   - `baselines` copies the earlier predictions and skips cases that already have one.

Teammates can each run the same notebook on their own account (with their own `secgate-code` upload) to use
their own weekly GPU quota. Share outputs by making the notebook version visible to the team, or by
downloading and re-uploading them as a dataset.

## 7. Get the results

- **In the browser:** open the notebook version, go to the *Output* tab, and download the files or the whole folder.
- **With the CLI:**
  ```bash
  kaggle kernels output <kaggle-user>/<notebook-slug> -p runs/<name>
  ```

What to look at:
- `outputs/smoke/throughput.json`: prefill/decode speed, gate-call time, prompt length, one agent task.
- `outputs/predictions/test/report.json`: per-condition decision mix. Until the human-labelled test set exists,
  the report shows decision mixes and heuristic sanity checks only, not accuracy.
- `outputs/logs/`: one log per GPU job, the first place to look when a job fails.
- `*.manifest.json` next to each output: code version, config hash, seed and library versions.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `attach the secgate-code dataset (no CODE_VERSION …)` | the dataset is not attached, or a version is still processing |
| `code version` shows an old commit | wait for the new dataset version to finish processing, then re-run |
| pip install / model download fails | Internet is off, or the account is not phone-verified |
| `CUDA out of memory` | the accelerator is not `GPU T4 x2`, or another process holds the GPU; restart the session |
| a GPU job exited non-zero | read `outputs/logs/<stage>/job<i>.log`; fix, re-upload the code, re-run with the old output attached |
| run stopped at 12 h | attach its output (step 6) and run the same stages again |
| output folder near 20 GB | delete `outputs/predictions/*/gate_cache/` (a cache only; it is rebuilt when needed) |
