# Security-Aware Tool-Using Agent — Human Labelling Branch

This branch holds the labelling tool and the 2,000 synthetic security-gate cases (20 batches of 100) that the team
labels by hand. No model code lives here.

```
labeling_app/            the labelling tool (run server.py, open the page)
  server.py              local server + JSON API; enforces who may write what
  index.html, app.js, app.css
  labels.py              vote storage and the multi-annotator rules
  merge.py               builds the main label database from everyone's votes
data/synthetic_data/
  batches/batch_XX.json  the cases (batch_XX.jsonl: same cases, one per line)
  batches/assignments.json   who labels which batch
  batches/annotations/<name>/batch_XX.json   your votes (you commit these)
  labels/                the main database, built by merge.py
resources/handbooks/     policy documents shown in the tool's policy search (placeholders for now)
scripts/prepare_batches.py   how the batches were made (reference only)
tests/test_labeling.py   end-to-end checks of the protocol
```

## The protocol in one paragraph

Every batch has **two primary annotators** who label all 100 cases independently and cannot see each other's
votes. When both have finished, a case where their votes differ on the **decision** or the **final action** is
**disputed**; the batch's **tie-break annotator** then votes on those cases only, and can see the two earlier votes.
Each vote is stored under its author's name in the author's own file, so nobody can change anyone else's vote and
files from different people never conflict in git. `merge.py` combines all votes into the main database: agreed
cases take the shared label, disputed cases the majority of the three votes.

## Assignments (`data/synthetic_data/batches/assignments.json`)

Each person is primary on 10 batches and tie-breaker on 4–6.

| Batch | Primary 1 | Primary 2 | Tie-break |
|---|---|---|---|
| 01 | rinkesh | prabhash | shubham |
| 02 | shubham | yogendra | rinkesh |
| 03 | rinkesh | shubham | prabhash |
| 04 | prabhash | yogendra | rinkesh |
| 05 | rinkesh | yogendra | prabhash |
| 06 | prabhash | shubham | yogendra |
| 07 | rinkesh | prabhash | shubham |
| 08 | shubham | yogendra | rinkesh |
| 09 | rinkesh | shubham | yogendra |
| 10 | prabhash | yogendra | shubham |
| 11 | rinkesh | yogendra | prabhash |
| 12 | prabhash | shubham | yogendra |
| 13 | rinkesh | prabhash | shubham |
| 14 | shubham | yogendra | rinkesh |
| 15 | rinkesh | shubham | prabhash |
| 16 | prabhash | yogendra | rinkesh |
| 17 | rinkesh | yogendra | prabhash |
| 18 | prabhash | shubham | yogendra |
| 19 | rinkesh | prabhash | shubham |
| 20 | shubham | yogendra | rinkesh |

## Labelling

```bash
git checkout labling && git pull
python labeling_app/server.py          # Python 3.10+, no extra packages
```

Open **http://localhost:8080**, pick your name once (it is remembered; click your name to switch, it asks
first), choose a batch from the batch menu (only your batches are listed, each with your role and progress), and
label one case at a time.

- **The card** shows what the user asked, what the agent wants to do (arguments copied from content are outlined
  amber, injected ones red) and four signals: origin, authority, data flow and arguments. `E` opens the full
  evidence: tool outputs and the retrieved policy clauses.
- **Decide** with the dock or `1`–`4`. ALLOW / BLOCK are done at once and move to the next unlabelled case.
  ASK_USER / ESCALATE open a sheet for the outcome, the missing evidence, who decides and (ASK_USER) the user's
  reply; *Done · next* (`Enter`) unlocks when the vote is complete. Your previous answers stay when you change
  your mind.
- **Every change saves immediately** — to your browser first and then to your vote file. If the server is not
  running, changes wait in the browser and are sent on the next load. The dot at the top right shows the state.
- The strip of ticks under the top bar is the batch: coloured by your decision, amber = started; click to jump.
- Tie-breakers see only the disputed cases, with both primary votes on the card.

| Field | Meaning |
|---|---|
| decision | first-round decision: **ALLOW** (enough trusted evidence, authorized) · **BLOCK** (prohibited, caused by or copying from instructions in untrusted content, or already declined/denied) · **ASK_USER** (something only the user can supply is missing: recipient, target, intent) · **ESCALATE** (needs a role the user does not hold) |
| final action | ALLOW or BLOCK after legitimate resolution with your *clean* user reply (equals the decision for ALLOW/BLOCK) |
| missing evidence | `none`, `user_intent`, `recipient_identity`, `resource_target`, `approval`, `data_classification` |
| required authority | `none`, `current_user`, `resource_owner`, `manager`, `security_admin` |
| user reply | ASK_USER only: one or two sentences in the user's voice, and whether it confirms; a reply can never grant authority |

- **Policies** (top bar, or `/`) opens the policy documents: browse every clause in `resources/handbooks/*.md` or
  search them. *cite* (there or in the evidence) adds a clause to your vote; cited clauses and an optional note sit
  at the bottom of the card. ASK_USER has an optional *noisy* reply variant (about 15% of ASK_USER cases).

| Key | Action |
|---|---|
| `1` `2` `3` `4` | ALLOW / BLOCK / ASK_USER / ESCALATE |
| `Enter` | done, next (when the vote is complete) |
| `→` `←` | next / previous case |
| `U` | next unlabelled case |
| `E` | show / hide the evidence |
| `/` | policy documents and search |
| `Esc` | leave a text field, close the policy panel |

## Sending your labels back

Commit only your own folder, then push:

```bash
git add data/synthetic_data/batches/annotations/<your-name>/
git commit -m "<your-name>: batch_XX labels"
git pull --rebase && git push
```

Push whenever you like (partial batches are fine); nothing you push can overwrite another person's votes.

**Tie-breakers:** after both primary annotators of your batch have pushed, `git pull` and open that batch — it
shows only the disputed cases, with both earlier votes above your vote form.

## Building the main database

```bash
git pull
python labeling_app/merge.py
```

This writes `data/synthetic_data/labels/`:

| File | Content |
|---|---|
| `cases.jsonl` | every case: status (`unlabeled`, `partial`, `agreed`, `awaiting_tiebreak`, `resolved`, `unresolved`) and its gold labels once decided |
| `gold.jsonl` | decided cases only — the labels the experiments use |
| `votes.jsonl` | every individual vote |
| `tiebreak_queue.json` | disputed cases still waiting, per batch and tie-breaker |
| `agreement.json` | Krippendorff's α and per-pair Cohen's κ on the two primary votes |

Everything in `labels/` is derived and can be regenerated at any time. `unresolved` (three different votes) is
left for a team decision.

## Policy documents

`resources/handbooks/workspace.md` and `banking.md` are **placeholders** assembled from the clause excerpts in
the batches. Replace them with the real handbooks (any `*.md` in that folder is indexed); keep each clause as a
`### [ID] Title` heading followed by its text.

## Checks

```bash
python -m pytest tests/test_labeling.py
```
