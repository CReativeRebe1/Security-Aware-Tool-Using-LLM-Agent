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
