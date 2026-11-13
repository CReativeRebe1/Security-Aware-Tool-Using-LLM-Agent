# SA-Gate demo website (Streamlit)

A website that shows what the project does, using **real Run 1 results**. It has five pages:

| Page | What it shows |
|---|---|
| Home | The problem, the gate idea, the four decisions, the project in numbers, headline results, a guide to the site |
| Playground | 7 hand-picked test cases told in six steps (request → agent → evidence → every gate's decision → right answer → live "try it"), guided with Back/Next or all on one page |
| Simulation | The gates race through the same real cases, animated in the browser: one square per case, live counters |
| Be the gate | A game: the visitor decides real test cases and is scored against B1, B5 and the newest gate |
| Gate Lab | The visitor designs a bank payment (payee, amount, where it came from, a fake approval note, their own answer) and the real pipeline handles it live |
| Explore all cases | Every test, dev and red-team case with each gate's result; filters, including "only this gate's mistakes" |
| How it works | Pipeline, evidence, RAG, the question loop, training, fair testing (tabs) |
| Results | B5 against the targets, the safety-vs-annoyance chart, every number, success by kind of case, links to each gate's mistakes, caveats |
| The research | Hypotheses and where they stand, how the dataset was built, experiments and run plan, project journey, known limits |

## Where the numbers come from

Nothing is copied or typed in. The app reads the repo's own files when it starts:

- `annotations/{test,dev}_cases.jsonl`: the frozen cases, with gold labels
- `results/data/run1/{test,dev}/*.jsonl` and `report*.json`: the recorded gate predictions and metrics
- `resources/handbooks/*.md`: the rule texts

When a new run is committed to `results/data/run1/` (for example B4), the site shows it automatically, with no
code change.

**Newest design (GateExp).** The GateExp branch is not merged into this branch. Its current run (B5 v2 inside the
GateExp layers: test, dev and the 61 red-team cases) is copied into `demo/data/gateexp/` by
`python demo/tools/sync_gateexp.py`, which also records the commit (`SOURCE.json`) and the 25 cases GateExp
relabelled (`relabels.json`). The site scores GateExp's predictions against the same frozen labels as every other
gate, and shows GateExp's own report (its labels, confirmations counted apart) next to it. Re-run the script
after a new GateExp run. On the red-team set, B1 is computed live with this branch's code.

**Final design (main).** The gate main's README reports as final (b5_v3_combo inside the GateExp layers: dev, the 61
red-team cases and 216 factor-combination cases, plus the live AgentDojo run) is copied into `demo/data/final/` by
`python demo/tools/sync_final.py`. It also copies the combination cases, the dev label differences
(`relabels.json`), the status of the final training runs A–D (`training_runs.json`) and the commit (`SOURCE.json`).
The final design has no test results on purpose (test is held back for one final run), so on the test set the site
shows GateExp v2 as the newest gate. When the final b5_v4_combo results land, run the script again with
`--cond`, `--run` and `--e2e` pointed at them. On the combination set, B1 is also computed live. `featured.yaml` holds the explanation text for the 7 Playground cases. Its result statements were
checked against the recorded predictions for code `da42a96`. Re-check them after a new run.

**Gate Lab:** only the conversation is made up (the user's words and what the bank tools return). The project's real
`ContextBuilder` turns it into evidence, exactly the way the 2,000 dataset cases were built, then `EvidenceMask`,
`RulesGate`/`GuardedGate`, the resolution loop and `MockApprover` run unchanged (`sagate_demo/lab.py`).

**Live part:** the B1 rules gate runs for real on the server (CPU only, `sagate_demo/gates.py`) through `sagate.eval.run_gate`'s path:
`EvidenceMask` → `RulesGate` / `GuardedGate` → resolution loop. With the default settings it reproduces the recorded
NB02 results exactly on all 448 test and dev cases. The AI gates (B2, B3, B5) are shown from their recorded results.
They need a GPU and come in phase 2.

## Run it locally

```bash
cd demo
python -m venv .venv && source .venv/bin/activate      # any Python 3.11+
pip install -r requirements.txt
streamlit run streamlit_app.py                          # opens http://localhost:8501
```

No GPU, torch or AgentDojo is needed. The app adds `../src` to the import path itself.

## Deploy on Streamlit Community Cloud (free)

1. Push the branch that holds `demo/` to GitHub.
2. On share.streamlit.io choose **Create app** and pick the repo, the branch and the main file
   `demo/streamlit_app.py`. Under *Advanced settings* choose Python 3.12.
3. Streamlit Cloud installs `demo/requirements.txt` (the file next to the main file), not the repo's
   `pyproject.toml`.
4. The app is public by default. To limit it, open the app's *Settings → Sharing* and allow only chosen viewers.

No secrets are needed in phase 1.

## Phase 2 (after the architecture is final): live B5

The plan is a Kaggle notebook that loads `unsloth/Qwen3-8B-bnb-4bit` plus the B5 adapter with the project's own
code (same bootstrap and code-hash check as NB04), and serves `GET /health`, `POST /gate` and `POST /resolve`
through FastAPI and an ngrok tunnel.
- The tunnel token and an API key go in **Kaggle Secrets**. The URL and key go in **Streamlit secrets**. Never
  put them in code.
- The app checks `/health` first and falls back to the recorded results if the server is off, so the demo
  cannot break.
- Run the server only during demo sessions, because it uses the shared Kaggle GPU quota.

## Files

```
demo/
  streamlit_app.py          entry point: top navigation bar, stylesheet, logo, footer
  views/                    the nine pages (home, playground, simulation, lab, game, explore, how_it_works, results,
                            research)
  sagate_demo/
    data.py                 loading only: cases, recorded predictions, reports, handbook, featured.yaml
    gates.py                where decisions come from: RecordedSource (Run 1 files) and LiveRulesSource (B1 now);
                            phase 2 adds RemoteSource (GPU server) here, with the same GateRun result
    explain.py              plain-language evidence summaries and the ✓/✕ verdict (same rules as eval/metrics.py)
    components.py           small HTML pieces (chips, cards, decision table, flows); all data text is escaped
    scenario.py             one case as six steps: guided (Back/Next) or all on one page
    lab.py                  Gate Lab engine: made-up conversation -> the project's real ContextBuilder and gate
    simulation.py           the race: payload from recorded predictions + a self-contained HTML/JS page
  assets/style.css          the design: colours, cards, chips, tables (classes start with sg-)
  assets/logo.svg, shield.svg  logo (top bar, footer); shield emblem (intro, home banner). hero.svg: unused
  featured.yaml             the 7 Playground scenarios and their explanations
  data/gateexp/             GateExp predictions, reports, red-team cases, relabels, SOURCE.json (copied, not merged)
  tools/sync_gateexp.py     refreshes data/gateexp from the GateExp branch
  data/final/               final-design predictions and reports, combination cases, live AgentDojo report,
                            dev label differences, training runs A–D status, SOURCE.json (copied from main)
  tools/sync_final.py       refreshes data/final from main
  requirements.txt          streamlit, plotly, pandas, pyyaml, numpy (pinned)
  .streamlit/config.toml    dark theme "Midnight": indigo brand on deep navy, Inter / JetBrains Mono (Google Fonts)
```

Chart colors (green = rules, orange = prompted AI, blue = trained AI) were checked for colour-blind safety. Every
chart also has direct labels or a table view.
