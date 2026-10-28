# Synthetic decision-only training cases (unlabeled)

2,000 hand-authored gate cases for the B4/B5 fine-tune, built over the AgentDojo **workspace** and **banking**
environments, the authority registries in `resources/authority/`, the sensitivity labels in
`resources/sensitivity/` and the two handbooks in `resources/handbooks/`. **No gold labels yet** — they are written
in the `Case` format (`src/sagate/data/cases.py`) with `pool: train`, `subset: decision_only`, all `gold_*` fields
`null`, ready for the existing annotation workflow.

Regenerate (deterministic, seed 42):

```bash
PYTHONPATH=src python -m sagate.train.synthetic check            # validate specs, print stats, write nothing
PYTHONPATH=src python -m sagate.train.synthetic build --n 2000   # writes the files below
```

## Files

| File | What it is |
|---|---|
| `cases.jsonl` | 2,000 `Case` rows (full `GateInput` with oracle provenance; inferred provenance in `alt_provenance`). Unlabeled. |
| `to_label.csv` | The same cases exported by `sagate.data.annotation export`: rendered evidence (`case_text`) + blank label columns. Give this to annotators. |
| `design_key.jsonl` | The case author's **intended** labels per case (decision, final action, missing_evidence, required_authority, clause IDs, rationale) and what the policy-state labeller (`train/variants.decide`) would say. **Keep it away from annotators** — use it only after labelling, to find authoring errors and hard cases. It is not gold. |
| `stats.json` | Counts by suite, category, round, intended decision, tool, difficulty; leakage and consistency checks. |
| `specs/*.yaml` | The hand-written source: 142 scenario families, 347 variants, 1,555 user prompts. Edit these, not the JSONL. |

## How the cases were written

Each **family** is one concrete situation — e.g. an auditor asking for the CONFIDENTIAL budget, a colleague's
address on a look-alike domain (`bluesparowtech.com`), an invoice whose new-payee IBAN comes from a document, a
payment split into 450 chunks to dodge the 500 limit, a "manager already approved this" note inside an email.
A family holds:

- the tool outputs the agent saw (real environment emails/files/events, or new hand-written content rendered in the
  exact AgentDojo YAML format),
- several hand-written user prompts (different wording, same intent),
- the proposed tool call,
- **contrastive variants** that change one fact so the right decision flips (internal vs external recipient, own
  vs someone else's file, 1,400 vs 1,850, user-given vs document-sourced IBAN, injected vs clean context).

Every realization is passed through the project's own `ContextBuilder`, so provenance / authority / sensitivity /
retrieved policy clauses come out exactly as the gate sees them at evaluation time.

Answered first rounds are included (`meta.round = 1`, 446 cases), with a `resolution_history`: the user
confirms, declines or gives an unhelpful answer; the approver (via `MockApprover`, as in evaluation) approves or
denies; or the user tries to authorize something herself ("I approve this") — which never counts as authority.

### Coverage (author's intended first-round decision, 1,554 cases)

| ALLOW | BLOCK | ASK_USER | ESCALATE |
|---|---|---|---|
| 581 (37%) | 449 (29%) | 313 (20%) | 211 (14%) |

Suites: 1,271 workspace / 729 banking. Categories: benign 515, ambiguity 630, injection 348, sensitivity 218,
authority 146, delegation 63, benign_with_injection 49 (hard negatives: injected text present but the call is the
user's own), authority_spoofing 31. 690 cases are tagged `difficulty: hard`. All 15 state-changing tools appear.

Injection is deliberately varied: fake IT notices, TODO lines in files, hidden HTML comments, messages that pretend
to be Emma, look-alike manager domains, German/Spanish instructions, reversed/obfuscated payloads, "SYSTEM
OVERRIDE" role-play, instructions in event location fields, transaction subjects and contact notes, multi-step
exfiltration (create a file, then share it), and payloads smuggled into otherwise legitimate payment references.

About 19% of cases are ones where the author's intent differs from the policy-state labeller — situations a
structured rule lookup gets wrong (split payments, a password suggested by a document the user delegated to,
customer lists exposed through the To: line, confidential lines pasted into an event description, user-named
files the rules would needlessly ask about). These are where human labels matter most.

## Leakage controls

- Every case is pool `train` (no scenario id) and passes `Splits.assert_pool(case, "train_only")`.
- Prompts were checked against every **test-pool** user-task prompt and injection goal: max 5-gram containment is
  0.33 (nothing above 0.5; such prompts would be dropped automatically). Situations that mirror test tasks
  (rent adjustment from `landlord-notices.txt`, Spotify price difference, follow-up meeting with the same
  participants, Hawaii packing list, recipe-to-grocery list, team-minutes TODO emails) were avoided.
- Attacker identities are new (none of AgentDojo's `mark.black-2134@gmail.com` / `US133000000121212121212`).

## Labelling workflow

Same protocol as the test set (proposal §5), using the existing tooling:

```bash
# 1. each annotator copies to_label.csv -> data/synthetic_data/to_label_<name>.csv and fills the label columns
PYTHONPATH=src python -m sagate.data.annotation agreement data/synthetic_data/to_label_*.csv
# 2. adjudicate disagreements into to_label_adjudicated.csv, then
PYTHONPATH=src python -m sagate.data.annotation gold data/synthetic_data/to_label_adjudicated.csv \
       --out annotations/synthetic_gold.jsonl
# 3. attach labels and write an NL training file (validated by train/nl_examples.py)
PYTHONPATH=src python -m sagate.train.synthetic merge --gold annotations/synthetic_gold.jsonl \
       --reviewer <member> --out annotations/synthetic_nl.jsonl
# 4. include it in SFT alongside the structured variants
PYTHONPATH=src python -m sagate.train.build_sft --cases outputs/sft/train_only_variants.jsonl \
       annotations/train_nl.jsonl annotations/synthetic_nl.jsonl
```

Notes for annotators:
- ASK_USER labels need `user_response_text` / `user_response_confirmed` (the NL validator enforces it). Every
  ASK_USER family has a hand-written confirm/decline reply in its spec (`replies:`) you can reuse.
- For `round 1` cases, label the decision **after** the answer shown in RESOLUTION HISTORY.
- Re-tag `category` to `authority_spoofing` if you spot an approval claim inside content that the author missed.
- Judgement calls where the handbook is ambiguous are marked `difficulty: hard` with a `why:` line in the spec
  (e.g. RESTRICTED data to an internal colleague, replying to an unknown sender the user named, a crypto payment the
  user asks for in her own words, sharing her own journal with a therapist). Disagreement there is expected; resolve
  it into the annotation guide.

## Extending

Add a family to any `specs/*.yaml` (see the header comment of `ws_01_email_disclosure.yaml` for the keys) or add
phrasings to an existing variant in `specs/*_extra_prompts.yaml`, then rerun `check`. The builder rejects unknown
tools, enum values, clause IDs and unresolved placeholders, and warns when the category disagrees with the computed
provenance (e.g. an "injection" case with no untrusted origin). Tests: `tests/test_synthetic.py`.
