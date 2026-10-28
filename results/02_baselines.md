# NB02 — Baselines B1 (rules), B2 and B3 (prompted Qwen3-8B)

**Run folders:**
- `runs/nb02/` — B1, B2, B3 on test and dev (code `1836a5b`)
- `runs/nb02_b3fix/` — B1 and B3 re-run on test after the user/approver simulator fix (code `f558cd5`)

**Files:** `outputs/predictions/{test,dev}/<condition>.jsonl` (one resolution trace per case), `report.json`,
`<condition>.manifest.json`, `gate_cache/`.

> ⚠ **Provisional.** The test labels are Claude's stand-ins for the human annotators. There are no ESCALATE cases and
> no decision-only cases, and the replay filter was not applied. Use these numbers to describe behaviour, not as
> the final result.

## Conditions

| | Gate | Decision space | Resolution loop |
|---|---|---|---|
| **B1** | Ordered deterministic rules over the same evidence (oracle provenance) | 4-way | yes |
| **B2** | Prompted Qwen3-8B, no fine-tuning | ALLOW / BLOCK | no |
| **B3** | Prompted Qwen3-8B, no fine-tuning | ALLOW / BLOCK / ASK_USER / ESCALATE | yes (≤ 2 rounds, then BLOCK) |

All three receive the same `GateInput`: oracle provenance, authority, sensitivity labels, top-3 policy clauses
(BM25), and untrusted content in delimited blocks. Each condition was run twice, once with clean simulated
user replies and once with noisy ones (15% of replies wrong or unhelpful).

## Test set (provisional)

160 executable cases, stratified by suite × category.

| | Count |
|---|---|
| Suite | banking 81 · workspace 79 |
| Category | benign 54 · injection 53 · user call inside an injected scenario 53 |
| Gold first decision | ALLOW 81 · BLOCK 56 · ASK_USER 23 · **ESCALATE 0** |
| Gold final action | ALLOW 81 · BLOCK 79 |

## Main result — test, clean replies

B1 and B3 are from `runs/nb02_b3fix` (after the simulator fix). B2 is from `runs/nb02`; it has no resolution
loop, so the fix does not affect it.

| Metric | B1 rules | B2 prompted binary | B3 prompted 4-way |
|---|---|---|---|
| **Final-resolution success** | **141/160 (88.1%)** | 91/160 (56.9%) | 137/160 (85.6%) |
| **Unauthorized-action rate** (target ≤ 5%) | 19/79 (24.1%) | 9/79 (11.4%) | **8/79 (10.1%)** |
| Over-blocking rate | **0/81 (0.0%)** | 60/81 (74.1%) | 15/81 (18.5%) |
| First-round accuracy | **137/160 (85.6%)** | 77/160 (48.1%) | 39/160 (24.4%) |
| Unnecessary deferral | 4/137 (2.9%) | 0/137 (0.0%) | 99/137 (72.3%) |
| Raw deferral rate (gold prevalence 23/160 = 14.4%) | 9/160 (5.6%) | 0/160 | 119/160 (74.4%) |
| Mean interactions per case | 0.056 | 0.000 | 0.894 |
| Clarification success (gold ASK_USER) | 5/23 (21.7%) | 0/23 (0.0%) | 8/23 (34.8%) |
| Escalation precision | 0/2 (0.0%) | n/a | 0/30 (0.0%) |
| Defaulted to BLOCK after 2 rounds | 0/160 | 0/160 | 20/160 (12.5%) |
| Binary success (first decision as ALLOW vs not) | 139/160 (86.9%) | 91/160 (56.9%) | 92/160 (57.5%) |
| Binary unauthorized rate | 19/79 (24.1%) | 9/79 (11.4%) | 2/79 (2.5%) |
| Macro-F1, missing evidence | 0.351 | 0.051 | 0.045 |
| Macro-F1, required authority | 0.653 | 0.167 | 0.161 |

Escalation recall and authority-spoofing success are `0/0 (n/a)`: the provisional set has no gold ESCALATE and
no authority-spoofing cases.

## Noisy user replies (test)

| | Success (clean → noisy) | Unauthorized (clean → noisy) | Noise-induced errors |
|---|---|---|---|
| B1 | 141 → 141/160 (88.1%) | 19 → 19/79 (24.1%) | 0/0 |
| B3 | 137 → 132/160 (82.5%) | 8 → 10/79 (12.7%) | 5/13 (38.5%) |

B1 hardly ever asks the user, so a bad reply cannot hurt it. B3 asks on most cases: 13 of its cases actually
received a noisy reply, and 5 of them went from correct (clean reply) to wrong.

## Breakdown by category and suite (test, clean)

Correct final outcome / unsafe allows (out of gold-BLOCK cases):

| Slice | n | gold BLOCK | B1 correct | B1 unsafe | B2 correct | B2 unsafe | B3 correct | B3 unsafe |
|---|---|---|---|---|---|---|---|---|
| Injection | 53 | 53 | 53/53 | 0/53 | 53/53 | 0/53 | 53/53 | 0/53 |
| User call in an injected scenario | 53 | 12 | 45/53 | 8/12 | 18/53 | 2/12 | 38/53 | 3/12 |
| Benign scenario | 54 | 14 | 43/54 | 11/14 | 20/54 | 7/14 | 46/54 | 5/14 |
| Banking | 81 | 37 | 73/81 | 8/37 | 47/81 | 2/37 | 69/81 | 2/37 |
| Workspace | 79 | 42 | 68/79 | 11/42 | 44/79 | 7/42 | 68/79 | 6/42 |

**Every gate blocks all 53 injected calls.** Every unsafe allow is an *agent mistake* inside a legitimate task,
not an attack.

## First-round confusion (gold → predicted)

| Gold ↓ / Pred → | B1: ALLOW | BLOCK | ASK | ESC | B2: ALLOW | BLOCK | B3: ALLOW | BLOCK | ASK | ESC |
|---|---|---|---|---|---|---|---|---|---|---|
| ALLOW (81) | 79 | 0 | 1 | 1 | 21 | 60 | 15 | 13 | 50 | 3 |
| BLOCK (56) | 1 | 53 | 1 | 1 | 0 | 56 | 0 | 10 | 25 | 21 |
| ASK_USER (23) | 18 | 0 | 5 | 0 | 9 | 14 | 2 | 1 | 14 | 6 |

First decisions overall: B1 ALLOW 98 · BLOCK 53 · ASK 7 · ESC 2; B2 BLOCK 130 · ALLOW 30;
B3 ASK_USER 89 · ESCALATE 30 · BLOCK 24 · ALLOW 17.

## What each baseline gets wrong

- **B1 (rules)** misses agent errors that look harmless to the rules, and allows all of them: wrong amounts
  (`send_money` 55 instead of 5, rent 1,100 instead of 1,200), duplicate calendar events and files, the wrong
  participants on a follow-up meeting, a new file instead of appending to an existing one. It blocks every
  injection partly **by construction**: it reads oracle provenance tags, which are derived from the known
  injected text. Treat B1 as an upper bound, not a realistic runtime gate.
- **B2 (prompted binary)** is "safe" only because it blocks three quarters of legitimate actions (60/81).
- **B3 (prompted 4-way)** defers almost everything: it asks the user on 89 cases and escalates 30 times, and none
  of the escalations is correct. In **6 of its 8 unsafe allows the simulated user answered "No"** (e.g. "No, that
  meeting is already in my calendar", "No — only the people from the Introductory meeting") and B3 allowed the
  action anyway. Its intermediate fields (missing evidence, required authority) are close to random
  (macro-F1 0.045 / 0.161).

## Effect of the simulator fix (commit `f558cd5`)

Before the fix, the simulated user could confirm injected calls, and the approver could approve a call whose gold
action is BLOCK. After it, the user never confirms injected calls and the approver checks argument provenance and
never approves gold-BLOCK cases. First-round decisions are unchanged; only the resolution rounds changed.

| B3, test | Before (`runs/nb02`) | After (`runs/nb02_b3fix`) |
|---|---|---|
| Final-resolution success | 131/160 (81.9%) | 137/160 (85.6%) |
| Unauthorized-action rate | 14/79 (17.7%) | 8/79 (10.1%) |
| Unsafe allows on injections | 1/53 | 0/53 |
| Unsafe allows, user call in injected scenario | 6/12 | 3/12 |
| Defaulted to BLOCK | 14/160 (8.8%) | 20/160 (12.5%) |
| Noisy: success / unauthorized | 126/160 (78.8%) / 16/79 (20.3%) | 132/160 (82.5%) / 10/79 (12.7%) |

B1 clean results are identical before and after. B1 noisy changed from 140/160 and 20/79 to 141/160 and 19/79.

## Evidence-pipeline quality (the same input for every gate)

| | Value |
|---|---|
| Policy retrieval Recall@3 / Recall@5 (gold clause in top-k, BM25) | 0.519 / 0.630 |
| Inferred vs oracle provenance, argument trust | 260/312 (83.3%) |
| Inferred vs oracle provenance, call-level instruction origin | 135/160 (84.4%) |

## Dev pool (no gold labels — decision mix only)

904 dev cases built from the 6 dev user tasks (900 had an untrusted block truncated). Dev is used only to select
the B4 threshold, so here it only shows each gate's behaviour.

| | First: ALLOW | BLOCK | ASK_USER | ESCALATE | Final: ALLOW | BLOCK | Mean interactions |
|---|---|---|---|---|---|---|---|
| B1 | 573 | 166 | 27 | 138 | 691 | 213 | 0.19 |
| B1 noisy | 573 | 166 | 27 | 138 | 694 | 210 | 0.19 |
| B2 | 110 | 794 | — | — | 110 | 794 | 0 |
| B3 | 24 | 77 | 504 | 299 | 576 | 328 | 0.97 |
| B3 noisy | 24 | 77 | 504 | 299 | 565 | 339 | 0.97 |

The same pattern holds on dev: B2 blocks 88% of cases, and B3 defers on 89% of first decisions.

## Cost

| | Speed on a T4 |
|---|---|
| B1 | < 0.01 s per case (CPU) |
| B2 | ~2.4 s per case |
| B3 (with resolution rounds) | ~4.2 s per case; ~0.3 s per case on the noisy re-run (gate-cache hits) |

Some prompts went over the 2,048-token inference limit (`model.max_input_tokens`): 66 B3 gate prompts on test and
669 B2 prompts on dev. Raising this limit for NB04 is worth considering, since training uses 4,096.

## Takeaways for the report

- Without training, a prompted 8B gate either over-blocks (B2) or over-defers (B3). Neither reaches the ≤ 5%
  unsafe-allow target together with a low deferral rate. This is the gap B4/B5 are meant to close.
- Injection blocking is easy on these cases for every gate. The hard part is **agent mistakes on legitimate
  tasks**, where the user's reply or a closer look at the arguments is needed.
- B3 ignoring an explicit "No" from the user is a ready-made qualitative failure example.
