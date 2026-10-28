# Annotations

Human labels for the test set (proposal §5). Files expected here:

| File | Written by | Content |
|---|---|---|
| `<batch>.csv` | `python -m sagate.data.annotation export` | cases to label (rendered evidence, blank label columns) |
| `<batch>_<annotator>.csv` | each annotator | the same CSV with label columns filled |
| `<batch>_adjudicated.csv` | team, after agreement is measured | final labels |
| `gold.jsonl` | `python -m sagate.data.annotation gold` | one row per case: `gold_*` fields + fixed `user_response` |
| `test_cases.jsonl`, `dev_cases.jsonl` | `python -m sagate.data.annotation freeze` | the frozen, gold-labelled case files NB02/NB04 evaluate (candidates + decision-only NL cases, gold attached, pool-checked) |
| `train_nl.jsonl` | NL authors | reviewed natural-language training examples |

Label columns: `gold_decision` (ALLOW / BLOCK / ASK_USER / ESCALATE), `gold_final_action` (ALLOW / BLOCK after
legitimate resolution), `gold_missing_evidence`, `gold_required_authority`, `gold_clause_ids` (comma-separated,
e.g. `BANK-2.2, BANK-6.2`), `user_response_text` + `user_response_confirmed` (yes / no) for ASK_USER cases.
Optional: `user_response_noisy_text` + `user_response_noisy_confirmed` (the wrong/unhelpful reply). `gold` marks a seeded
15% of user replies noisy; where no noisy reply was written it uses an unhelpful one. Edit the `category` column to
`authority_spoofing` for cases where untrusted content claims an approval — that tag drives the spoofing metric.

Agreement: `python -m sagate.data.annotation agreement annotations/batch1_*.csv` (Krippendorff's α + pairwise κ).
