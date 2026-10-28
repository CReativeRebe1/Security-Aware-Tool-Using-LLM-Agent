# Labelled synthetic training cases

Gold labels for the 2,000 synthetic decision-only cases in [`../synthetic_data/`](../synthetic_data/), produced with the
project's own annotation tooling, so every file here is in the format the pipeline already reads.

| File | What it is | Used by |
|---|---|---|
| `synthetic_nl.jsonl` | **The training file.** 2,000 `Case` rows with `gold_*` fields, fixed `user_response` for every ASK_USER case, `meta.reviewed_by`. Passes `sagate.train.nl_examples check`. | `train.build_sft` (B4/B5 + ablations) |
| `labelled.csv` | Same labels in the annotation CSV format (`to_label.csv` with the label columns filled; `notes` = rationale). Edit this to change a label. | `data.annotation gold` |
| `synthetic_gold.jsonl` | Output of `annotation gold` on `labelled.csv` (seeded 15% of user replies marked noisy). | `train.synthetic merge` |
| `cases.jsonl` | The unlabelled cases the labels attach to: `../synthetic_data/cases.jsonl` with one fix (see correction 1). | `train.synthetic merge` |
| `review_log.csv` | The 50 cases whose label differs from the author's design key, with the reason. | review |

## Label mix

| | ALLOW | BLOCK | ASK_USER | ESCALATE |
|---|---|---|---|---|
| First decision, round 0 (1,554) | 577 | 449 | 317 | 211 |
| First decision, answered round 1 (446) | 140 | 113 | 91 | 102 |
| Final action (2,000) | 1,236 | 764 | — | — |

408 ASK_USER cases carry a fixed user reply (266 confirm, 142 decline). 77 of them are marked noisy.

## How the labels were made

These labels were **not** made by two human annotators. They are the case author's intended labels
(`../synthetic_data/design_key.jsonl`), reviewed by Claude (Opus 5.5) against the rendered evidence of each case.
`meta.reviewed_by` is `claude-opus-5.5`. The proposal only needs training labels "checked by a second member", so
**a team member should still spot-check them**, starting with `review_log.csv` and the `difficulty: hard` cases.
They are training labels only: never use these cases as test data (all are pool `train`).

Review steps:
1. Checked all 616 distinct situations (family × variant × answered round). Labels never vary across prompt
   paraphrases of the same situation.
2. Read every situation where the design key disagrees with the rule-based labeller (`train/variants.decide`):
   111 situations, 377 cases.
3. Flagged every label that contradicts the evidence: ALLOW with untrusted provenance, ALLOW without authority and
   without an approval, ALLOW on a high-to-low flow without an approval, an ESCALATE role that differs from the
   authority registry, ASK_USER without a missing-evidence value. All ALLOW-on-high-to-low hits were cases after a real
   manager approval, which is correct. The rest are corrected below.
4. Read every user "confirm" reply alongside the call it confirms.

Fixed user replies come from each family's hand-written `replies:` in the specs. A case whose final action is
ALLOW gets the confirm reply; one whose final action is BLOCK gets the decline reply. The noisy variant is the
family's unhelpful reply.

## Corrections to the design key (50 cases)

1. **The confirm reply is really a correction** (5 families: `bank-iban-typo-of-known/one-digit-off`,
   `ws-ask-typed-address/{lookalike-domain, missing-letter-internal}`,
   `ws-minutes-to-client/look-alike-domain-colleague`, `ws-share-lookalike-from-sharelist/lookalike`).
   - The "yes" reply says *"Typo — I mean david.smith@bluesparrowtech.com"*, but the proposed call still goes to the
     mistyped external address or IBAN, and the design key had ALLOW.
   - New labels: the answered round is BLOCK. The round-0 and unhelpful-reply cases keep ASK_USER but their final
     action becomes BLOCK, with the correction as the fixed (declining) reply.
   - In `cases.jsonl`, `confirmed` in those answered rounds is set to `false`.
2. **`ws-ask-several-johns/picked-personal-friend`**: sending the client meeting minutes (INTERNAL) to a personal
   friend's gmail needs manager approval even if the user confirms it.
   - The answered "yes" round becomes ESCALATE (manager) with final action BLOCK.
   - The round-0 case keeps ASK_USER with final action BLOCK. Its reply is that the user meant John Mitchell, the client.
3. **`ws-invite-from-email/approved-personal-sender`**: the user asks to invite "the events guy", but the email
   comes from `lily.white@gmail.com` and is signed Rafael. ALLOW becomes ASK_USER (recipient_identity), with final
   action ALLOW.

## Use it

```bash
# training data for all 8 trained conditions (add the structured variants / other NL files as usual)
PYTHONPATH=src python -m sagate.train.build_sft --cases outputs/sft/train_only_variants.jsonl \
       data/labled-data/synthetic_nl.jsonl
# after editing labelled.csv, rebuild:
PYTHONPATH=src python -m sagate.data.annotation gold data/labled-data/labelled.csv --out data/labled-data/synthetic_gold.jsonl
PYTHONPATH=src python -m sagate.train.synthetic merge --cases data/labled-data/cases.jsonl \
       --gold data/labled-data/synthetic_gold.jsonl --reviewer <name> --out data/labled-data/synthetic_nl.jsonl
```

`kaggle/stage_code.sh` ships `synthetic_nl.jsonl` in the code bundle, and NB03 adds it to the training cases
automatically when it is present.
