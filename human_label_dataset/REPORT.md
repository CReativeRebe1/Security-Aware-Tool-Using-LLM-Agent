# Human label dataset

**1500 of 2,000 cases have a final human label; 0 wait for a team call (see [DECISIONS.md](DECISIONS.md)); 500 are not reviewed yet.**

Built by `python human_label_dataset/build.py` from the reviews committed on the `labeling` branch.

## Tiers

| Tier | Meaning | Cases | ALLOW | BLOCK | ASK_USER | ESCALATE |
|---|---|---|---|---|---|---|
| A | two careful reviews agree | 481 | 180 | 130 | 97 | 74 |
| B | one careful review | 1005 | 357 | 291 | 200 | 157 |
| T | decided by the team | 11 | 1 | 5 | 2 | 3 |
| C | only fast reviews (unchecked) | 3 | 0 | 2 | 1 | 0 |
| | **all** | **1500** | 538 | 428 | 300 | 234 |

A review is *fast* when it was saved less than 3 s after the reviewer's previous save, too quick to read the case. Exception: prabhash labelled these cases earlier with the previous labelling schema and re-marked the same labels in the review tool, so those reviews count as careful.

**For the final evaluation use tiers A + B + T.** Tier C labels are the suggested labels accepted without being read; treat them as unchecked until someone reviews them properly.

## Reviewers

| Reviewer | Reviews | Accepted | Edited | Can't label | Fast saves | Same as suggestion |
|---|---|---|---|---|---|---|
| prabhash | 1000 | 1000 | 0 | 0 | 98% | 100% |
| rinkesh | 504 | 496 | 4 | 4 | 0% | 98% |
| yogendra | 500 | 483 | 17 | 0 | 4% | 99% |
| shubham | 0 | – | – | – | – | – |

Batches with both reviews: 01, 04, 05, 11, 13, 17. With one: 02, 03, 06, 07, 10, 12, 16, 18, 19. With none: 08, 09, 14, 15, 20.

## Agreement (cases reviewed by both)

501 cases; decision agreement 99.4%, Krippendorff's α 0.992. Agreement is inflated: almost every review accepts the same suggested label, so this mostly measures agreement with the suggestion, not two independent judgements.

## Known issues

- 414 final labels keep a suggested explanation that the suggestions reuse for different decisions (written per scenario family, not per case); `explanation_is_family_template` marks them. The decision fields are what counts; check those explanations before using them as training targets.
- Reviewer comments are kept in `reviewer_comments`, never inside `explanation`.

## Name variation

Every case in the source data uses the same people (the user is always Emma Johnson), which a model can learn as a shortcut. Each case's `input`, `explanation` and `user_response` therefore use their own set of names (`names.py`): consistent inside the case, first and last names mapped separately (so "which Sarah?" cases stay ambiguous), typos kept as typos, domains and company names unchanged. `name_map` holds the mapping, so it can be undone. Labels do not change, because no rule depends on a person's name.

## Files

| File | Content |
|---|---|
| `final/human_labels.jsonl` | one row per labelled case: gold fields, user reply (clean + noisy), explanation, tier, every review, reviewer comments, the case `input` (names varied) and `name_map` |
| `final/pending.jsonl` | reviewed cases waiting for a call in `decisions.json` |
| `final/summary.json` | all numbers in this report |
| `decisions.json` / `DECISIONS.md` | the open calls with both labels, a recommendation and the reason |
