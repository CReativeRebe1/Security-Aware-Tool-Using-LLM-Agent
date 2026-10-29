# What is not run yet

B4 and B5 are trained ([03_training.md](03_training.md)) and evaluated ([04_learned_gates.md](04_learned_gates.md)).
The code for the rest exists and was tested locally on Qwen3-0.6B (plumbing checks only, not results). Add a
`05_*.md` / `06_*.md` file per phase as the runs come in.

| Phase | What it will produce | Needs | Status |
|---|---|---|---|
| NB03 — 6 ablation adapters | `b5_no_prov`, `b5_no_auth`, `b5_no_rag`, `b5_no_ask`, `b5_no_esc`, `b5_no_inter`, 1 epoch each | ~6–7.5 h per adapter on a T4, so 3 sessions of 2 in parallel (~20 GPU-h) | Not run; timing only |
| NB04 — ablations | The 6 ablations on test (Holm–Bonferroni in NB06) | The ablation adapters | Not run; B4 / B5 done |
| NB05 — end-to-end AgentDojo | B0 vs B5 on the 142 test scenarios: utility, ASR, leakage, tool selection, argument validity | B5 adapter | Not run (B0 side done in NB01) |
| NB06 — statistics and report | Paired bootstrap 95% CIs, exact McNemar, Holm–Bonferroni over ablations, Pareto frontier, qualitative examples | NB04 + NB05 predictions | Not run (CPU only) |

## Blocking items before results are reportable

1. **Human gold test set.** Two annotators label `annotations/batch1.csv` (160 executable cases). Measure agreement
   (Krippendorff's α ≥ 0.667, pairwise κ), adjudicate, and freeze.
2. **~84 decision-only test cases**, with at least 30 ESCALATE. Without them, B4 vs B5 on escalation cannot be
   measured, because the executable cases contain 0 ESCALATE.
3. **AgentDojo replay filter** on the test cases (locally, 75 of 1,390 candidates did not reproduce in v1.2.2).
4. Re-run NB02 and NB04 on the frozen set. NB03 does not need re-running: the adapters do not depend on the test labels.

## Deviations from the proposal to state in the final report

- 1 QLoRA epoch instead of 2 (measured 111–143 s per step on a T4).
- Training max length 2,560 instead of 4,096 (T4 out of memory at ~3.8k tokens); drops 15 (B5) / 8 (B4) of 3,000
  generated examples.
- The dev pool (B4 threshold) is rule-labelled generated variants: its ASK_USER cases are about recipient identity
  (59/60), while most test ones are about user intent (16/23), so dev safety numbers do not predict test ones
  (see [04_learned_gates.md](04_learned_gates.md)).
- User/approver simulator fix (`f558cd5`) before the final baseline numbers.
- B1 uses oracle provenance, so its injection blocking is an upper bound.
- Handbooks are about 2 pages each instead of 5–8, so Recall@k (0.52 @3, 0.63 @5) covers few clauses.
- Training labels: rule-generated variants plus author-labelled synthetic cases reviewed by Claude, not
  two-annotator labels.
