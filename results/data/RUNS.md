# Runs

Every evaluation and training run, oldest first. **Final** marks the runs the reported numbers come from
(summary: `docs/report/gate_report.pdf`; full log with analysis: `docs/GATE_EVALUATION.md`).

| Folder | Date | What | Model | Code | Labels |
|---|---|---|---|---|---|
| `run1/` | 2026-11-10 | Run 1: baselines B1–B5 on the frozen dev / test (NB02, NB03, NB04) | b5_qlora_4way | da42a96 | original |
| `2026-11-11_gateexp_run1_b5/` | 2026-11-11 | Live: B5 inside GateExp (test, dev, attacks; clean + noisy) | b5_qlora_4way | 9661a73 | original |
| `2026-11-11_gateexp_v2_b5v2/` | 2026-11-11 | Live: retrained B5 v2 inside GateExp | b5_v2 | ce86875 | original |
| `2026-11-11_replay_credential_flow/` | 2026-11-11 | CPU replay: + credential_flow rule | b5_qlora_4way, b5_v2 | ce86875 + rule | original |
| `2026-11-11_gateexp_final_b5v2_credential/` | 2026-11-11 | Live proof run: B5 v2 + GateExp + credential_flow | b5_v2 | ce86875-dirty | new payee = confirm |
| `2026-11-12_gateexp_ledger_b5v2/` | 2026-11-12 | Live: ledger fixes + payment principle (owner-personal rule and 4 relabels later reverted) | b5_v2 | ce86875-dirty-ledger | + amount relabel |
| `2026-11-12_gateexp_tags_ab_b5v2/` | 2026-11-12 | Live A/B: clause coverage tags off (`notags/`) vs on (`tags/`) | b5_v2 | ce86875-dirty-tagsab | + amount relabel |
| `2026-11-12_custom_user_cases_b5v2/` | 2026-11-12 | Live: the 10 user-supplied cases (`annotations/extra/`) | b5_v2 | 85d872d | – |
| **`2026-11-12_train_b5v3/`** | 2026-11-12 | **Final** training: summaries of b5_v3 and b5_v3_combo (NB03) | b5_v3, b5_v3_combo | 11eadd8 | + amount relabel |
| **`2026-11-12_compare_b5v3_vs_combo/`** | 2026-11-12 | **Final** selection run: dev, combos, attacks, user cases (clean) | b5_v3, b5_v3_combo | 11eadd8 | + amount relabel |
| `2026-11-12_e2e_smoke/` | 2026-11-12 | NB05 smoke: 2 AgentDojo scenarios per GPU per model | b5_v3, b5_v3_combo | 11eadd8 | – |
| **`2026-11-12_replay_review_fixes/`** | 2026-11-12 | **Final** CPU replay of the selection run through the review fixes (`.base` = before, `.new` = after) | b5_v3, b5_v3_combo | review fixes | + amount relabel |
| **`2026-11-12_e2e_agentdojo_b5v3/`** | 2026-11-12 | **Final** live AgentDojo: 142 test scenarios, noisy user (gate before the review fixes) | b5_v3_combo, b5_v3 | 11eadd8 | – |
| `2026-11-12_replay_review2_gate_fixes/` | 2026-11-12 | CPU replay: review-2 gate fixes (approval ≠ user confirmation, untraced target, amount parser) | b5_v3, b5_v3_combo | aad241f | + amount relabel |
| `2026-11-12_replay_step2_policy_labels/` | 2026-11-12 | CPU replay: handbook clauses BANK-2.8/2.9, WS-2.10/2.11, intent verbs, combos/dev relabels, strict unneeded-ask metric | b5_v3, b5_v3_combo | step 2 | + review-2 relabels |

Each folder: `<pool>/<condition>[_noisy].jsonl` predictions, `.report.json` metrics, `.decision_log.jsonl` (facts,
rule steps and model answer per round), `.manifest.json`. AgentDojo folders hold `traces.jsonl` per condition.
Results from before Run 1 (2026-10-29, synthetic-label phase) are in `results/archive/2026-10-29/`.
