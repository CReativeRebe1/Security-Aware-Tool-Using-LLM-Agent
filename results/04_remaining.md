# Phases not run yet (NB04 – NB06)

The code for these phases exists and was tested locally on Qwen3-0.6B (plumbing checks only, not results). The
GPU runs on the 8B model have not happened yet. Fill this file in, or split it into `04_*.md`, `05_*.md` and
`06_*.md`, as the runs come in.

| Phase | What it will produce | Needs | Status |
|---|---|---|---|
| NB03 (full) | Trained adapters for B4, B5 and the 6 ablations, 1 epoch each | ~6–7.5 h per adapter on a T4 | Not run; timing only (see [03_training.md](03_training.md)) |
| NB04 — learned-gate evaluation | B4 threshold picked on dev, then B4 vs B5 on test (H1/H2); ablations; inferred-provenance swap; clean vs noisy | NB03 adapters + frozen gold test set | Not run |
| NB05 — end-to-end AgentDojo | B0 vs B5 on the 142 test scenarios: utility, ASR, leakage, tool selection, argument validity | B5 adapter | Not run (B0 side done in NB01) |
| NB06 — statistics and report | Paired bootstrap 95% CIs, exact McNemar, Holm–Bonferroni over ablations, Pareto frontier, qualitative examples | NB04 + NB05 predictions | Not run (CPU only) |

## Blocking items before results are reportable

1. **Human gold test set.** Two annotators label `annotations/batch1.csv` (160 executable cases). Measure agreement
   (Krippendorff's α ≥ 0.667, pairwise κ), adjudicate, and freeze.
2. **~84 decision-only test cases**, with at least 30 ESCALATE. Without them, B4 vs B5 on escalation cannot be
   measured, because the executable cases contain 0 ESCALATE.
3. **AgentDojo replay filter** on the test cases (locally, 75 of 1,390 candidates did not reproduce in v1.2.2).
4. Re-run NB02 on the frozen set. NB03 does not need re-running: the adapters do not depend on the test labels.

## Deviations from the proposal to state in the final report

- 1 QLoRA epoch instead of 2 (measured 111–143 s per step on a T4).
- User/approver simulator fix (`f558cd5`) before the final baseline numbers.
- B1 uses oracle provenance, so its injection blocking is an upper bound.
- Handbooks are about 2 pages each instead of 5–8, so Recall@k (0.52 @3, 0.63 @5) covers few clauses.
- Training labels: rule-generated variants plus author-labelled synthetic cases reviewed by Claude, not
  two-annotator labels.
