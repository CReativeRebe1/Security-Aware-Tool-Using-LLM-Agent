# Results — Security-Aware Tool-Using LLM Agent (SA-Gate)

Results of every phase that has run so far, taken from the Kaggle run outputs in `runs/`. One file per phase:

| Phase | File | Kaggle run folder(s) | State |
|---|---|---|---|
| NB00 — setup, smoke test, throughput | [00_setup_smoke.md](00_setup_smoke.md) | `runs/nb00/`, `runs/diag/` | Done |
| NB01 — B0 agent traces (Qwen3-8B, no gate) | [01_b0_traces.md](01_b0_traces.md) | `runs/nb01/`, `runs/nb01_run1/` | Done |
| NB02 — baselines B1 (rules), B2 / B3 (prompted) | [02_baselines.md](02_baselines.md) | `runs/nb02/`, `runs/nb02_b3fix/`, `runs/nb02_dev/` | Done on **provisional** labels |
| NB03 — training data, timing run, B4 / B5 training | [03_training.md](03_training.md) | `runs/nb03_timing/`, `runs/nb03_v2/` (failed), `runs/nb03_v3/` | B4 + B5 trained (1 epoch); ablations not trained |
| NB04 — learned gates B4 / B5 | [04_learned_gates.md](04_learned_gates.md) | `runs/nb04/` | Done on **provisional** labels; no ablations |
| NB03/NB04 ablations, NB05, NB06 | [05_remaining.md](05_remaining.md) | — | Not run yet |

**Final predictions in the repo:** `runs/` is git-ignored, so the predictions behind every reported number are copied to
[`data/`](data/):

| Path | Contents |
|---|---|
| `data/test/` | One file per gate on the 160 test cases: B1, B3 (after the simulator fix, `runs/nb02_b3fix`), B2 (`runs/nb02`), B4, B4 matched, B5, B5 inferred provenance (`runs/nb04`); clean and noisy; `report.json` covers all of them |
| `data/dev/` | B1–B3 (`runs/nb02_dev`) and B4 / B5 (`runs/nb04`) on the 300 labelled dev cases, `b4_threshold.json`, `report.json` |
| `data/training/` | `train_summary.json` of the B4 and B5 adapters (dropped ids, loss curve, runtime) |

To rebuild a report: `PYTHONPATH=src python3 -m sagate.eval.report --cases annotations/test_cases.jsonl --pred results/data/test/*.jsonl`
(for dev, `--cases` is NB03's `outputs/sft/dev_cases.jsonl` from `runs/nb03_v3`).

All numbers are raw counts with percentages, as the proposal asks (`8/79 (10.1%)`).

> **Read this before quoting anything.** The NB02 and NB04 test numbers use **provisional labels made by Claude**, standing
> in for the two human annotators (`annotations/claude/README.md`). They have no ESCALATE cases, no decision-only
> cases, and the AgentDojo replay filter was not applied. They show how the pipeline behaves, but they are **not
> the reportable result**. Re-run NB02 and NB04 once the human gold set is frozen (the adapters do not need retraining).
> NB00 and NB01 do not depend on labels, so their numbers are final.

---

## Setup in one paragraph

- **Model:** Qwen3-8B, pre-quantised 4-bit (`unsloth/Qwen3-8B-bnb-4bit`, nf4, fp16 compute, thinking off), used as both
  the task agent and the gate.
- **Hardware:** Kaggle, 2 × Tesla T4 (16 GB), one job per GPU.
- **Benchmark:** AgentDojo v1.2.2, `banking` and `workspace` suites, `important_instructions` attack.
- **Split** (seed 42, fixed before anything was generated): user tasks 28 train / 6 dev / 22 test. Strict scenarios are
  276 train and 142 test; 342 are excluded.
- **Software:** Python 3.13, torch 2.11.0+cu128, transformers 4.57.6, peft 0.20.0, bitsandbytes 0.50.2, agentdojo 0.1.35.

## Headline numbers so far

| What | Result | Phase | Final? |
|---|---|---|---|
| B0 task success (utility), test pool | **49/142 (34.5%)** — benign 8/22, attacked 41/120 | NB01 | Yes |
| B0 attack success rate (ASR) | **10/120 (8.3%)** — banking 8/24, workspace 2/96 | NB01 | Yes |
| B0 sensitive-data leakage | 0/142 | NB01 | Yes |
| Best baseline: correct final outcome | B1 rules **141/160 (88.1%)** | NB02 | Provisional |
| Best baseline: unsafe actions allowed | B3 prompted 4-way **8/79 (10.1%)** (target ≤ 5%) | NB02 | Provisional |
| **B5 (QLoRA 4-way): correct final outcome** | **140/160 (87.5%)** (B3 85.6%) | NB04 | Provisional |
| **B5: unsafe actions allowed** | **15/79 (19.0%)**; 14 of the 15 are user-intent should-ask cases it did not ask about | NB04 | Provisional |
| B5: over-blocking / needless questions | 5/81 (6.2%) / 18/137 (13.1%) (B3: 18.5% / 72.3%) | NB04 | Provisional |
| B4 (QLoRA binary) at the dev-matched threshold | success 103/160 (64.4%), unsafe 13/79 (16.5%), over-blocking 44/81 (54.3%) | NB04 | Provisional |
| Injected calls blocked | 53/53 by every gate (B1–B5) | NB02/04 | Provisional |
| B5 with inferred instead of oracle provenance | success 121/160 (75.6%), over-blocking 26/81 (32.1%) | NB04 | Provisional |
| B5 on the dev pool | success 277/300 (92.3%), unsafe 7/128 (5.5%); B4 accepts 10/12 spoofed approvals, B5 0/12 | NB04 | Generated labels |
| Policy retrieval Recall@3 / Recall@5 | 0.519 / 0.630 | NB02 | Provisional |
| Inferred vs oracle provenance agreement | 260/312 arguments (83.3%) | NB02 | Provisional |
| QLoRA step time on a T4 (8B, 3,000 examples) | 111–143 s per step → 5.8–7.4 h per epoch | NB03 | Yes (timing) |
| Trained 8B adapters | **2 of 8** (B4, B5; 1 epoch, 5 h 50 min each, 15 / 8 of 3,000 examples dropped at 2,560 tokens) | NB03 | Yes |

## Experimental conditions

| Condition | Gate | Decisions | Status |
|---|---|---|---|
| B0 | none (agent alone) | — | Run (NB01) |
| B1 | deterministic rules | 4-way (+ binary projection) | Run (NB02) |
| B2 | prompted Qwen3-8B | ALLOW / BLOCK | Run (NB02) |
| B3 | prompted Qwen3-8B | ALLOW / BLOCK / ASK_USER / ESCALATE | Run (NB02) |
| B4 | QLoRA Qwen3-8B | ALLOW / BLOCK, threshold on `p_allow` | Trained and run (NB03 / NB04) |
| B5 | QLoRA Qwen3-8B | 4-way + resolution loop | Trained and run (NB03 / NB04) |
| B5 ablations | −provenance, −authority, −RAG, −ASK, −ESCALATE, −intermediate | | Timing run only |

## Metric glossary

| Metric | Meaning |
|---|---|
| Final-resolution success | Final ALLOW/BLOCK (after any ASK_USER / ESCALATE rounds) equals the gold final action |
| Unauthorized-action rate | Gold-BLOCK cases the gate ended up allowing ("unsafe allows"); target ≤ 5% |
| Over-blocking rate | Gold-ALLOW cases the gate ended up blocking |
| Unnecessary deferral | Cases asked/escalated although gold says no deferral was needed |
| First-round accuracy | First decision equals the gold four-way label |
| Clarification success | Gold ASK_USER cases resolved correctly |
| Escalation precision | Escalations the gold label agrees with |
| Defaulted to block | Still deferring after 2 rounds, so blocked by default |
| Noise-induced error rate | Of the cases that received a noisy user reply: correct with the clean reply but wrong with the noisy one |
| Utility / ASR | AgentDojo user-task success / injection-task success |

## Code version of each run

| Run | Git commit staged on Kaggle | Date |
|---|---|---|
| `runs/diag` | `9d42cd2` | 2026-10-26 |
| `runs/nb00` | `9772e83` | 2026-10-26 |
| `runs/nb01_run1` (first attempt, OOM) | before `ac20d80` | 2026-10-26 |
| `runs/nb01` | `bf8f1ec` | 2026-10-26 |
| `runs/nb02` | `1836a5b` | 2026-10-28 |
| `runs/nb03_timing` | `1836a5b` | 2026-10-28 |
| `runs/nb02_b3fix` | `f558cd5` | 2026-10-28 |
| `runs/nb03_v2` (failed: out of memory, stale code) | `f558cd5` | 2026-10-28 |
| `runs/nb03_v3` (B4 + B5 training) | `73cc6a4` | 2026-10-28 → 29 |
| `runs/nb04` (B4 / B5 evaluation, no ablations) | `73cc6a4` | 2026-10-29 |
| `runs/nb02_dev` (B1–B3 on the labelled dev pool) | `73cc6a4` | 2026-10-29 |
