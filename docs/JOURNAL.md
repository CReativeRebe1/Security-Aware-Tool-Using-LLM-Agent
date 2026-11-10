# Project Journal — Security-Aware Tool-Using LLM Agent

A running record of what we built, what we found, what we decided and why. Newest entries go at the bottom of
each section; numbers are raw counts with percentages. Branch for the current work: `valhalla`.

## Timeline

| Date | Step | Result |
|---|---|---|
| 2026-10-26 | AgentDojo workspace + banking exported; scenario split fixed (seed 42) | `dataset` branch: 56 user tasks, 23 injection tasks, 760 scenarios, 23,602 logged traces |
| 2026-10-26 → 30 | Team builds the pipeline (`main`): evidence, gates B1–B5, resolution loop, Kaggle notebooks | B0: utility 49/142 (34.5%), attack success 10/120 (8.3%) |
| 2026-10-29 | First B4/B5 results on 160 Claude-labelled AgentDojo cases (provisional) | B5: 87.5% correct, 19.0% unsafe, 13.1% unneeded asks; target not met |
| 2026-11-06 → 09 | Human review of 2,000 synthetic cases; split frozen by scenario family | `HumanLabelDataset`: train 1,049 · dev 236 · test 212 (39 ESCALATE) |
| 2026-11-09 | Retrieval experiment (`RagExp`, not merged) | Recall@5 0.630 → 0.781 on test (target 0.85) |
| 2026-11-09 | Pipeline audit against the frozen data | Findings below; led to the `valhalla` branch |
| 2026-11-10 | Fixes, new evidence and guards on `valhalla` (8 commits) | Rules gate on frozen test: unsafe 21.2% → 10.2% |
| 2026-11-10 | Frozen data wired in; parallel training groups; run guide (`docs/RUN_GUIDE.md`) | CPU dry run passes; leak guard refuses test cases in training |
| 2026-11-10 | Kaggle smoke test (NB07), all stages on 2 × T4, account `satorugojo13` | 11/11 stages pass in ~17 min |
| 2026-11-10 | Retrieval: evidence words + fact-to-clause index fused with BM25, 8 clauses | Dev Recall@8 0.946 (was Recall@3 ~0.41) |

## Audit findings (2026-11-09)

| Finding | Effect | Status |
|---|---|---|
| NB03 still trains on the old 2,000-case file, which contains all 212 frozen test cases | Test leaks into training | Fixed: frozen splits converted, old file no longer staged, training refuses held-out cases |
| Running an action without the required approval scored as correct | Hid unsafe actions; favoured B4 | Fixed (`57f4363`) |
| Pre-answered rounds visible to gates that cannot ask (B4, B2, −ASK, −ESCALATE) | Free evidence for those gates | Fixed (`569bbb9`) |
| −authority ablation still saw authority through retrieval and history | Underestimates H1 | Fixed (`569bbb9`) |
| One injected line tainted a whole tool output | User's own calls blocked with inferred provenance | Fixed (`3682193`) |
| Quiet injections (no suspicious wording) look trusted | 220 of 230 missed on train+dev with inferred provenance | **Open:** partly addressed by trust degree, scope check, counterfactual |
| NB04/NB05 load adapters from one NB03 run | Ablations silently missing | Fixed: adapters collected from every attached NB03 kernel |
| Bootstrap/McNemar treat cases as independent (212 cases, 21 families) | Intervals too narrow | **Open:** before NB06 |

## Decisions

| Decision | Reason |
|---|---|
| Use only the frozen `HumanLabelDataset` labels | Team decision; later reviews flagged and excluded |
| Skipped ESCALATE counts as unauthorized; skipped ASK_USER is not success and is reported as "executed without confirmation" | Same call can get "yes" or "no"; the gate cannot see the reply, so luck must not score |
| Gates that cannot defer train to BLOCK on deferral cases | Otherwise B4 is trained to execute without approval |
| Keep the policy limits as written: 1,500 per known payee, 500 per new payee, 5,000 manager maximum | Confirming every payment would have cost 23.7% needless asks |
| Add a rolling 24 h cumulative limit of 5,000 | Stops repeated payments by a hijacked agent; one benchmark task = one window |
| A split payment counts as the full amount the user asked for (BANK-2.4) | 9 test cases were split payments passing per-piece checks |
| Guards only make ALLOW stricter, reported separately as `b5_guarded` | Keeps the learned gate's own result clean |
| Read-only tools bypass the gate | They change nothing; only 97 of 483 B0 calls were state-changing |
| Do not tighten injection phrase cues | Would drop detection of `direct` attacks from 98.6% to 16.3% |
| Uneven costs (needless ask vs wrong payment) handled with a weighted score at the end | Predictions keep every decision, so it needs no re-run |
| No more design changes on test numbers; design on train+dev, run test once | Avoid leaking test information through us |
| B5 with guards is the main candidate | Best estimated chance of meeting the 5% unsafe target |
| Train 2 epochs instead of 1 | Training set is now ~2,050 examples, so 2 epochs (8–10 h) fit one session; same for every condition |
| Run 1 = B5/B4 + baselines; ablations only after the team agrees on Run 1 | Ablations must compare against the final B5 |
| Retrieval = BM25 + evidence words + fact index (built from training labels only), 8 clauses | Dev Recall@5 0.55 → 0.76, Recall@8 0.95; each condition retrieves only from evidence it may see |
| Index from generated cases alone is not enough (covers 20 of 48 clauses, Recall@5 0.64) | Generated per-clause coverage cases will be a supplement at lower weight, not a replacement |
| Retrieval fallbacks: no index → BM25 + evidence words; handbook edited → stale index ignored with a warning | A deployment never silently uses a wrong index; full write-up in `experiments/rag/REPORT_INDEX.md` (branch RagExp) |
| Training max length 2,560 → 3,072 tokens | Longer prompts: 121 of 1,000 variants would be dropped at 2,560, 8 at 3,072; smoke test trains on the longest examples first |

## What was added on `valhalla`

| Commit | Change |
|---|---|
| `57f4363` | Scoring: skipped approvals/confirmations are failures; new "executed without confirmation" metric |
| `569bbb9` | Evidence feeder (per-condition toggles); checks `amount_source`, `duplicate`, `trust_degree`, `action_requested` |
| `3682193` | Inferred provenance taints only the injected passage; numbers matched loosely |
| `767140b` | Guards: limits, placeholders, repeated calls, invented amounts, cumulative limit; `b5_guarded` |
| `524cf8f` | Live: counterfactual probe ("would this happen without the user?"), executed-payment tracking, chunked long-prompt scoring; `b5_counterfactual` |
| `db817f9` | Three-view scope check for outgoing actions (user / action / third party) |
| `a074c1d` | Split payment checked against the full amount asked for |
| `c6eec05` | Review fixes: approver named on escalation, `needs_confirmation` as evidence only, −provenance leak, B4 matched on same cases, checks refreshed after replies |

## Results log (rules gate B1 on the frozen test, oracle provenance)

| Stage | Correct | Unsafe (≤ 5%) | Unneeded asks (≤ 10%) |
|---|---|---|---|
| B1, new scoring | 183/212 (86.3%) | 25/118 (21.2%) | 0/127 (0%) |
| + guards and scope check | 190/212 (89.6%) | 18/118 (15.3%) | 10/127 (7.9%) |
| + split-payment rule | — | 9/118 (7.6%) | — |
| + review fixes (scope confirmation as evidence only) | 196/212 (92.5%) | 12/118 (10.2%) | 0/127 (0%) |

These are rules-gate simulations, not B5. Several were checked on the test set during diagnosis; the report must say so.

## Tried and rejected

| Idea | Why rejected |
|---|---|
| Confirm every one-off payment | 23 of 97 good actions would become needless asks |
| Tighter injection phrase list | Large recall loss on `direct` and `ignore_previous` attacks |
| Rewriting `action_requested` (3 versions) | All worse: in user-intent cases the user does ask for the action; the doubt is about details |
| Temperature scaling for B4 | Does not change ranking, so cannot help threshold matching |

## Ideas credited to related work

- Counterfactual check: MELON (arXiv 2502.05174) and AgentSentry (arXiv 2602.22724). Our addition: routing the result to ALLOW / ASK_USER / BLOCK.
- Argument-level provenance: PACT. Provenance graph: Agent-Sentry. Information flow: Fides.

## Open items

| Item | When |
|---|---|
| Generate per-clause coverage cases for the index (supplement for rare clause combinations) | After Run 1 |
| Action trail (hop-counted degree built from the real call chain) | After the run |
| Degree rule in the gate prompt + guard for degree ≥ 2 | After the run |
| Family-level bootstrap | Before NB06 |
| Calibrate counterfactual threshold on train scenarios | Before NB05 |
| Loop round count; clean replies in NB05; live payee trust | Later |
| Weighted cost score; report notes (test diagnosis, B4 74% ceiling, deviations) | Final report |
