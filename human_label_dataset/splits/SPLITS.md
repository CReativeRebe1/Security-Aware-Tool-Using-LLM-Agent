# Frozen split

Split by scenario family (seed 42): every case of a family is in one split, so no paraphrase or answered round of a test situation is ever trained on. The family assignment is frozen in `family_split.json`; rerunning `freeze_split.py` reuses it.

| | Train | Dev (validation) | Test |
|---|---|---|---|
| Cases | 1049 | 236 | 212 |
| Families | 97 | 24 | 21 |
| ALLOW | 373 | 89 | 76 |
| BLOCK | 304 | 71 | 51 |
| ASK_USER | 202 | 51 | 46 |
| ESCALATE | 170 | 25 | 39 |
| Final ALLOW / BLOCK | 638 / 411 | 149 / 87 | 133 / 79 |
| Banking / workspace | 388 / 661 | 70 / 166 | 76 / 136 |
| Answered-round cases | 230 | 49 | 53 |
| Not reviewed yet (join later) | 354 | 68 | 81 |

| Category | Train | Dev | Test |
|---|---|---|---|
| ambiguity | 316 | 82 | 68 |
| authority | 83 | 8 | 21 |
| authority spoofing | 7 | 8 | 5 |
| benign | 271 | 52 | 61 |
| benign with injection | 27 | 7 | 4 |
| delegation | 32 | 11 | 9 |
| injection | 193 | 37 | 28 |
| sensitivity | 120 | 31 | 16 |

Every row carries `pool` (`train`, `dev` or `test`), the tag the pipeline's leakage guard checks on decision-only cases. Only tiers A, B and T are used; the 2 tier-C cases wait for a careful review.

File hashes are in `MANIFEST.json`.
