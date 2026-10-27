# SaGate Human Labelling Interface 🛡️

A dedicated, high-productivity web application for annotating synthetic gate cases across the 20 batches of 100 cases.

## Quick Start

1. Ensure you are on the `labling` branch:
   ```bash
   git branch
   # * labling
   ```

2. Start the local labelling server:
   ```bash
   python3 labeling_app/server.py
   ```

3. Open your browser to:
   ```
   http://localhost:8080
   ```

---

## Features

- **Batch Partitioning**: All 2,000 synthetic cases are shuffled (seed `42`) and split into **20 batches of 100 cases** (`batch_01` to `batch_20`).
- **Ergonomic Workspace**:
  - **Left**: Detailed Security Context, User Request, Proposed Call, Provenance, Authority & Sensitivity, Untrusted Tool Outputs (prompt injection detector), and Retrieved Policy Clauses.
  - **Right**: 4-way decision cards (`ALLOW`, `BLOCK`, `ASK_USER`, `ESCALATE`) with conditional evidence fields.
- **Instant Keyboard Shortcuts**:
  - `1`, `2`, `3`, `4`: Select decision
  - `Enter`: Save and jump to next case
  - `[` or `←`: Previous case
  - `]` or `→`: Next case
  - `U`: Jump directly to next unlabeled case
  - `G`: Toggle the 1–100 Case Switcher grid
  - `R`: Toggle between Structured View and Raw LLM Prompt View
  - `?`: Open keyboard shortcut guide
- **Auto-Sync & Export**:
  - Real-time auto-saving directly to `data/synthetic_data/batches/annotations/<batch_id>_<annotator>.json` and `.csv`.
  - Automatic `localStorage` backup for offline safety.
  - One-click **Export CSV** producing exact files compatible with the project's annotation agreement pipeline.

---

## Downstream Annotation Pipeline

Once you or your teammates complete a batch, use the project's CLI tools:

```bash
# Measure inter-annotator agreement
PYTHONPATH=src python3 -m sagate.data.annotation agreement data/synthetic_data/batches/annotations/batch_01_*.csv

# Build gold labels from adjudicated batch
PYTHONPATH=src python3 -m sagate.data.annotation gold data/synthetic_data/batches/annotations/batch_01_adjudicated.csv --out annotations/synthetic_gold.jsonl
```
