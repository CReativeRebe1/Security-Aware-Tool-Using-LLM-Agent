# GateExp runs (branch GateExp)

| Folder | Date | What | Model | Code | Labels |
|---|---|---|---|---|---|
| `2026-11-11_gateexp_run1_b5/` | 2026-11-11 | Live run: B5 inside GateExp (test, dev, attacks; clean + noisy) | B5 run-1 adapter (b5_qlora_4way) | 9661a73 | original |
| `2026-11-11_gateexp_v2_b5v2/` | 2026-11-11 | Live run: retrained B5 v2 inside GateExp | b5_v2 (weighted loss, dropout 0.1, augmented) | ce86875 | original |
| `2026-11-11_replay_credential_flow/` | 2026-11-11 | Offline replay from saved scores: + credential_flow rule (no GPU) | both adapters | ce86875 + rule | original |
| `2026-11-11_gateexp_final_b5v2_credential/` | 2026-11-11 | **Proof run** (live): B5 v2 + GateExp + credential_flow | b5_v2 | ce86875-dirty (rule + relabel) | C1 relabel (new payee = confirm) |

Each folder: `<pool>/<condition>[_noisy].jsonl` predictions, `.report.json` metrics, `.decision_log.jsonl`
(facts, rule steps, model answer per round), `.manifest.json`. Results and analysis: docs/GATE_EVALUATION.md.
`run1/`, `dev/`, `test/`, `training/` are the earlier Run 1 results (valhalla).
| `2026-11-12_gateexp_ledger_b5v2/` | 2026-11-12 | Live: B5 v2 + GateExp + ledger fixes + payment principle (owner-personal rule and 4 history relabels later reverted) | b5_v2 | ce86875-dirty-ledger | C1 + amount relabel |
| `2026-11-12_gateexp_tags_ab_b5v2/` | 2026-11-12 | Live A/B: same code, clause coverage tags off (`notags/`) vs on (`tags/`), clean responses | b5_v2 | ce86875-dirty-tagsab | C1 + amount relabel (history cases restored) |
| `2026-11-12_train_b5v3/` | 2026-11-12 | NB03 full run: train summaries of b5_v3 and b5_v3_combo | – | 11eadd8 | C1 + amount relabel |
| `2026-11-12_compare_b5v3_vs_combo/` | 2026-11-12 | Live selection run: b5_v3 vs b5_v3_combo inside GateExp on dev, combos, attacks, user cases (clean) | b5_v3, b5_v3_combo | 11eadd8 (+ NB08 compare mode) | C1 + amount relabel |
| `2026-11-12_e2e_smoke/` | 2026-11-12 | NB05 smoke (2 scenarios per GPU per condition): live AgentDojo with GateExp | b5_v3, b5_v3_combo | 11eadd8 | – |
| `2026-11-12_replay_review_fixes/` | 2026-11-12 | CPU replay of the selection-run answers through the review fixes (`.base` = current code, `.new` = fixes) | b5_v3, b5_v3_combo | 11eadd8 + review fixes | C1 + amount relabel |
