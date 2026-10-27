# SaGate — Human Labeling Branch

> **Branch purpose:** Human annotation of 2,000 synthetic security-gate cases.  
> This branch contains **only** the labeling tool and data — no model code, no training pipelines.

---

## What's in this branch

```
labeling_app/        ← Web UI (open this in your browser)
  server.py          ← Local server — run this first
  final.html         ← ✅ Recommended annotation interface
  index.html         ← Classic 2-column layout
  compact.html       ← Compact dual-pane reviewer
  minimal.html       ← Zen minimal style
  speed.html         ← Speed triage (keyboard-only)
  wireframe.html     ← Structured form layout

data/synthetic_data/batches/
  batch_01.json ... batch_20.json   ← 20 batches × 100 cases each
  batch_XX_to_label.csv             ← Per-batch CSV (fill these)
  annotations/                      ← Your saved labels go here (SQLite)
  manifest.json                     ← Batch metadata & progress tracking
  shuffled_index.json               ← Reproducible shuffle seed

scripts/
  prepare_batches.py   ← How the batches were created (reference only)
```

---

## How to start labeling

### 1. Clone and switch to this branch

```bash
git clone https://github.com/CReativeRebe1/Security-Aware-Tool-Using-LLM-Agent.git
cd Security-Aware-Tool-Using-LLM-Agent
git checkout labling
```

### 2. Start the local server

```bash
cd labeling_app
python3 server.py
```

You should see:
```
🚀 SaGate Human Labelling Interface Server running!
👉 Local URL: http://localhost:7861
```

### 3. Open the annotation interface

Go to **http://localhost:7861/final.html** in your browser.

> You can also try other styles at `http://localhost:7861` — the footer links switch between all designs.

---

## How to annotate

### Pick your name
Select your name from the **annotator dropdown** in the top bar (Rinkesh / Prabhash / Shubham / Yogendra).  
Your annotations are saved separately per annotator.

### Pick your batch
Each person should work on different batches. Choose from the **batch dropdown**.

| Annotator | Suggested Batches |
|-----------|------------------|
| Rinkesh   | 01–05            |
| Prabhash  | 06–10            |
| Shubham   | 11–15            |
| Yogendra  | 16–20            |

### Make a decision for each case

For each case you will see:
- **User Request** — what the user asked the AI agent to do
- **Proposed Tool Call** — what tool the agent wants to call, with arguments
- **Security Signals** — authority, data flow, approver info
- **Retrieved Policies** — relevant security policy clauses

Pick one of these four labels:

| Label | Keyboard | Meaning |
|-------|----------|---------|
| `ALLOW` | `1` | The tool call is safe and the user is clearly authorized |
| `BLOCK` | `2` | Violates a policy, prompt injection detected, or unauthorized |
| `ASK_USER` | `3` | Ambiguous — the agent should ask the user to clarify |
| `ESCALATE` | `4` | Needs a manager or resource owner to approve |

### Extra fields (only appear when needed)

- **ASK_USER** → select what's missing (user intent, recipient identity, etc.) and optionally write a simulated reply
- **ESCALATE** → select who needs to approve (manager / resource_owner / security_admin)
- **Cited Policies** → click `+ Cite` on any policy that influenced your decision
- **Notes** → optional rationale

### Save and move on

Click **Save & Next** or press `Enter` to save and go to the next case.

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `1` / `2` / `3` / `4` | Set decision |
| `Enter` | Save & next case |
| `← →` or `[ ]` | Navigate cases |
| `U` | Jump to next unlabeled case |
| `Ctrl+Enter` | Save while typing in a text field |

---

## Where are my annotations saved?

Annotations are saved to a local **SQLite database** at:

```
labeling_app/annotations.db
```

The file is **git-ignored** — it lives only on your machine.

When you're done with a batch, use the **Export CSV** button to download your labels as a CSV file, and share it with the team (or commit the CSV).

---

## Data format (for reference)

Each case in a batch JSON looks like this:

```json
{
  "case_id": "bank_allow_001",
  "suite":   "banking",
  "category": "routine",
  "difficulty": "easy",
  "raw_case": {
    "input": {
      "user":          { "principal_id": "emma", "prompt": "..." },
      "proposed_call": { "function": "send_money", "args": {...}, "state_changing": true },
      "authority":     { "principal": "emma", "approver": null, ... },
      "sensitivity":   { "resource": "INTERNAL", "destination": "EXTERNAL" },
      "policy_clauses":[{ "id": "B-PAY-01", "title": "...", "text": "..." }],
      "provenance":    [{ "arg": "amount", "trust": "trusted" }]
    }
  }
}
```

---

## Questions?

Reach out to **Rinkesh** or raise an issue on the repo.
