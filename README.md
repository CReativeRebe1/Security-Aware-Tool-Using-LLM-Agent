# Security-Aware Tool-Using Agent — Human Review Branch

This branch holds the review tool and the 2,000 synthetic security-gate cases (20 batches of 100) that the team
checks by hand. No model code lives here.

```
labeling_app/            the review tool (run server.py, open the page)
  server.py              local server + JSON API; enforces who may write what
  index.html, app.js, app.css
  labels.py              review storage and the two-reviewer rules
  merge.py               builds the main label database from everyone's reviews
data/synthetic_data/
  batches/batch_XX.json  the cases (batch_XX.jsonl: same cases, one per line)
  batches/suggestions.json   the suggested decision + explanation for every case
  batches/assignments.json   the two reviewers of each batch
  batches/annotations/<name>/batch_XX.json   your reviews (you commit these)
  labels/                the main database, built by merge.py
resources/handbooks/     policy documents (placeholders for now)
scripts/prepare_batches.py   how the batches were made (reference only)
tests/test_labeling.py   end-to-end checks of the protocol
```

## The protocol in one paragraph

Every case comes with a **suggested decision and explanation**. Each batch is reviewed by **exactly two people**,
and nobody else can open it or write to it. The two review all 100 cases independently and cannot see each
other's reviews. For each case a reviewer **accepts** the suggestion, **edits** it (decision, outcome, missing
evidence, who decides, user reply, explanation), or marks it **can't label** with a reason and a note. When both
have reviewed a case it is **agreed** if their decision and final action match; otherwise it is **disputed**, and
the two talk it over and each revises their own review. Each review is stored under its author's name in the
author's own file, so nobody can change anyone else's review and files from different people never conflict in git.

## Phases and assignments (`data/synthetic_data/batches/assignments.json`)

The 20 batches are split into **two phases of 10 batches**. In each phase every person reviews **5 batches**, and
every batch has **2 reviewers**. Finish phase 1 first; at the end of each phase the reviews are combined with
`merge.py` (see below).

The split was chosen so both phases have the same kind of data: difficulty is identical (345 hard / 655 medium
cases each), and suite, category, follow-up rounds and suggested decisions differ by only a few cases.

| Phase | Batch | Reviewer 1 | Reviewer 2 |
|---|---|---|---|
| 1 | 02 | shubham | yogendra |
| 1 | 03 | rinkesh | shubham |
| 1 | 04 | prabhash | yogendra |
| 1 | 05 | rinkesh | yogendra |
| 1 | 06 | prabhash | shubham |
| 1 | 11 | rinkesh | yogendra |
| 1 | 12 | prabhash | shubham |
| 1 | 13 | rinkesh | prabhash |
| 1 | 17 | rinkesh | yogendra |
| 1 | 18 | prabhash | shubham |
| 2 | 01 | rinkesh | prabhash |
| 2 | 07 | rinkesh | prabhash |
| 2 | 08 | shubham | yogendra |
| 2 | 09 | rinkesh | shubham |
| 2 | 10 | prabhash | yogendra |
| 2 | 14 | shubham | yogendra |
| 2 | 15 | rinkesh | shubham |
| 2 | 16 | prabhash | yogendra |
| 2 | 19 | rinkesh | prabhash |
| 2 | 20 | shubham | yogendra |

| Person | Phase 1 batches | Phase 2 batches |
|---|---|---|
| rinkesh | 03, 05, 11, 13, 17 | 01, 07, 09, 15, 19 |
| prabhash | 04, 06, 12, 13, 18 | 01, 07, 10, 16, 19 |
| shubham | 02, 03, 06, 12, 18 | 08, 09, 14, 15, 20 |
| yogendra | 02, 04, 05, 11, 17 | 08, 10, 14, 16, 20 |

## Reviewing

```bash
git checkout labeling && git pull
python labeling_app/server.py          # Python 3.10+, no extra packages
```

Open **http://localhost:8080**, pick your name once (it is remembered; click your name to switch), and choose a
batch from the batch menu (only your 10 batches are listed, grouped by phase, with your progress). The screen has three columns and
nothing scrolls:

- **Left — the case:** what the user asked, what the agent wants to do (arguments copied from content are outlined
  amber, injected ones red), four signals (origin, authority, data flow, arguments) and any earlier conversation.
- **Middle — the evidence:** the untrusted tool outputs and the retrieved policy clauses, always visible. If a tool
  output is very long, *open full text* shows all of it.
- **Right — your review:** the suggested decision with its explanation, and three choices:
  - **Accept** (`A`) — the suggestion is right; saved and you move on.
  - **Reject & edit** (`R`) — change the decision (`1`–`4`), outcome, missing evidence, who decides, the user's
    reply (ASK_USER) and the explanation. The suggested values are marked with •. Save with the button,
    `Enter`, or `Ctrl+Enter` inside the explanation.
  - **Can't label** (`C`) — the case does not fit any of the four decisions or is broken. Pick a reason (unclear
    request, evidence missing, evidence contradicts itself, none of the 4 decisions fits, not a security decision,
    duplicate or broken case, other) and write a short note.

Every save goes straight to your review file. The strip under the top bar is the batch: green = accepted,
purple = edited, striped amber = can't label; click a tick to jump. You can reopen any case and change your review.

| Field | Meaning |
|---|---|
| decision | first-round decision: **ALLOW** (enough trusted evidence, authorized) · **BLOCK** (prohibited, caused by or copying from instructions in untrusted content, or already declined/denied) · **ASK_USER** (something only the user can supply is missing: recipient, target, intent) · **ESCALATE** (needs a role the user does not hold) |
| final action | ALLOW or BLOCK after legitimate resolution with the *clean* user reply (equals the decision for ALLOW/BLOCK) |
| missing evidence | `none`, `user_intent`, `recipient_identity`, `resource_target`, `approval`, `data_classification` |
| required authority | `none`, `current_user`, `resource_owner`, `manager`, `security_admin` |
| user reply | ASK_USER only: one or two sentences in the user's voice, and whether it confirms; a reply can never grant authority |
| explanation | why this is the right decision (required) |

| Key | Action |
|---|---|
| `A` | accept the suggestion |
| `R` | reject & edit (or change your review) |
| `C` | can't label |
| `1` `2` `3` `4` | in the editor: ALLOW / BLOCK / ASK_USER / ESCALATE |
| `Enter` / `Ctrl+Enter` | save and go to the next unreviewed case |
| `→` `←` | next / previous case |
| `Esc` | cancel the editor, close the full-text view |

## Sending your reviews back

Commit only your own folder, then push:

```bash
git add data/synthetic_data/batches/annotations/<your-name>/
git commit -m "<your-name>: batch_XX reviews"
git pull --rebase && git push
```

Push whenever you like (partial batches are fine); nothing you push can overwrite another person's reviews.

**Disputed cases:** after both reviewers of a batch have pushed, run `merge.py` (below) and look at
`labels/phase_N/disputed.json`. The two reviewers discuss each listed case and update their own reviews in the tool until
they agree.

## Combining the data at the end of a phase

```bash
git pull
python labeling_app/merge.py
```

It prints a progress table per phase and writes `data/synthetic_data/labels/`:

| Folder / file | Content |
|---|---|
| `phase_1/` | the 10 batches of phase 1 |
| `phase_2/` | the 10 batches of phase 2 |
| `combined/` | both phases together (after phase 1 it holds phase 1's data; after phase 2, everything) |
| `summary.json` | per phase: batches, case counts per status, and `finished` (every case agreed or can't label) |

Each folder holds the same files:

| File | Content |
|---|---|
| `cases.jsonl` | every case: phase, batch, status (`unlabeled`, `partial`, `agreed`, `disputed`, `cannot_label`), its two reviewers, and its gold labels once agreed |
| `gold.jsonl` | agreed cases only — the labels the experiments use |
| `votes.jsonl` | every individual review |
| `disputed.json` | cases where the two reviewers disagree, per batch |
| `cannot_label.json` | cases both reviewers marked can't label, with their reasons and notes (fix or drop them) |
| `agreement.json` | Krippendorff's α and Cohen's κ between the two reviewers |
| `label_mix.json` | gold decisions, final actions, suites and categories, to compare the two phases |

A phase is done when `merge.py` shows it as finished: every case agreed or can't label, no disputes left.
Everything in `labels/` is derived and can be regenerated at any time.

## Policy documents

`resources/handbooks/workspace.md` and `banking.md` are **placeholders** assembled from the clause excerpts in
the batches. Replace them with the real handbooks (any `*.md` in that folder is indexed); keep each clause as a
`### [ID] Title` heading followed by its text.

## Checks

```bash
python -m pytest tests/test_labeling.py
```
