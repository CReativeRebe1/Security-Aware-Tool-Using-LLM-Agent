# NB03 — Training data, QLoRA timing run, and full B4 / B5 training

**Run folders:**
- `runs/nb03_timing/` (code `1836a5b`): timing run, all 8 conditions for 20 optimizer steps each (~0.11 epoch)
- `runs/nb03_v2/` (code `f558cd5`): first full attempt, **failed** (see §4)
- `runs/nb03_v3/` (code `73cc6a4`): **full training of B4 and B5, 1 epoch each**, the adapters used in NB04

Each folder holds `outputs/sft/` (training files per condition) and `outputs/adapters/<condition>/`
(`train_summary.json`, `manifest.json`, PEFT adapter).
**Hardware:** Kaggle, 2 × T4, one condition per GPU.

**B4 and B5 are fully trained** (§4). The 6 ablations have only the 20-step timing run, so they have no results yet.

## 1. Training data

Each condition is trained on the **same 3,000 examples**; only the evidence mask and the label space differ:

| Source | Examples | How the labels were made |
|---|---|---|
| Structured policy variants (`train.variants`, train-only scenarios) | 1,000 | Rule-based policy-state labeller over full evidence |
| Hand-authored synthetic decision-only cases (`data/labled-data/synthetic_nl.jsonl`) | 2,000 | Author's design key, reviewed by Claude (50 corrections); still needs a human spot-check |
| **Total per condition** | **3,000** | |

### Structured variants

| | Train-only pool | Dev pool (B4 threshold only) |
|---|---|---|
| Seed proposals → candidate cases → sampled | 2,929 → 9,814 → **1,000** | 559 → 2,023 → **300** |
| First-round gold mix | ALLOW 280 · BLOCK 240 · ASK_USER 160 · ESCALATE 120 | ALLOW 105 · BLOCK 90 · ASK_USER 60 · ESCALATE 45 |
| Answered-round (2nd decision) examples | 200 (ALLOW 142 · BLOCK 53 · ASK_USER 5) | 0 |
| Final action mix | ALLOW 628 · BLOCK 372 | ALLOW 172 · BLOCK 128 |

Policy mutations applied to the 1,000 train variants (unmutated seeds: 426):

| Mutation | n | Mutation | n |
|---|---|---|---|
| `participant_from_content` | 101 | `over_limit` | 45 |
| `inject` | 84 | `new_payee` | 38 |
| `recipient_from_content` | 69 | `external_recipient` | 29 |
| `spoof_approval` | 69 | `over_manager_max` | 27 |
| `internal_recipient` | 27 | `redirect_standing_order` | 24 |
| `payee_from_document` | 20 | `delete_others` | 20 |
| `append_readonly` | 16 | `share_external` | 4 |
| `share_rw_others` | 1 | | |

### Hand-authored synthetic set (2,000)

| | ALLOW | BLOCK | ASK_USER | ESCALATE |
|---|---|---|---|---|
| First decision, round 0 (1,554) | 577 | 449 | 317 | 211 |
| First decision, answered round 1 (446) | 140 | 113 | 91 | 102 |
| Final action (2,000) | 1,236 | 764 | — | — |

408 ASK_USER cases carry a fixed user reply (266 confirm, 142 decline), and 77 of those replies are marked noisy.

### Target decision per condition (3,000 examples each)

| Condition | ALLOW | BLOCK | ASK_USER | ESCALATE | Change vs B5 |
|---|---|---|---|---|---|
| `b5_qlora_4way` (B5) | 1,139 | 855 | 573 | 433 | — |
| `b4_qlora_binary` (B4) | 1,864 | 1,136 | — | — | target = gold final action |
| `b5_no_prov` | 1,139 | 855 | 573 | 433 | provenance masked |
| `b5_no_auth` | 1,139 | 855 | 573 | 433 | authority masked |
| `b5_no_rag` | 1,139 | 855 | 573 | 433 | policy clauses masked |
| `b5_no_ask` | 1,523 | 1,044 | — | 433 | ASK_USER → gold final action |
| `b5_no_esc` | 1,480 | 947 | 573 | — | ESCALATE → gold final action |
| `b5_no_inter` | 1,139 | 855 | 573 | 433 | no intermediate fields in the target |

## 2. Training configuration

| Setting | Value |
|---|---|
| Base model | `unsloth/Qwen3-8B-bnb-4bit` (nf4), fp16 compute |
| Trainer | transformers `Trainer` + PEFT, loss on the assistant JSON only |
| LoRA | r = 16, α = 32, dropout 0.05, on q/k/v/o/gate/up/down projections |
| Batch | 1 × gradient accumulation 16 (effective 16) |
| Learning rate | 2e-4, cosine, warm-up 3%, gradient clipping 0.3 |
| Max length | 4,096 tokens in the timing run; **2,560** for the full run (commit `73cc6a4`, see §4) |
| Epochs | 2 in the timing run's config; **1** for the full run (commit `e676c47`) |
| Steps per epoch | 3,000 / 16 = 187.5 → ~188 |

## 3. Timing run results (20 steps per condition)

| Condition | Median tokens | Max tokens | Train tokens (1 epoch) | 20 steps (min) | s / step | Loss @10 | Loss @20 | 1 epoch | 2 epochs |
|---|---|---|---|---|---|---|---|---|---|
| `b5_qlora_4way` | 1,244 | 3,825 | 3,961,838 | 47.6 | 142.7 | 0.288 | 0.070 | 7.4 h | 14.9 h |
| `b4_qlora_binary` | 1,168.5 | 3,751 | 3,738,399 | 37.1 | 111.4 | 0.307 | 0.081 | 5.8 h | 11.6 h |
| `b5_no_prov` | 1,140 | 3,635 | 3,621,046 | 42.1 | 126.2 | 0.254 | 0.070 | 6.6 h | 13.1 h |
| `b5_no_auth` | 1,161 | 3,709 | 3,705,989 | 36.9 | 110.8 | 0.303 | 0.073 | 5.8 h | 11.5 h |
| `b5_no_rag` | 1,091.5 | 3,678 | 3,507,977 | 41.4 | 124.3 | 0.275 | 0.068 | 6.5 h | 12.9 h |
| `b5_no_ask` | 1,205 | 3,787 | 3,847,265 | 38.5 | 115.6 | 0.295 | 0.075 | 6.0 h | 12.0 h |
| `b5_no_esc` | 1,207 | 3,789 | 3,852,972 | 46.2 | 138.6 | 0.289 | 0.078 | 7.2 h | 14.4 h |
| `b5_no_inter` | 1,167 | 3,749 | 3,734,088 | 37.3 | 112.0 | 0.391 | 0.111 | 5.8 h | 11.7 h |

Epoch projections = 187.5 steps × measured s/step, and exclude model loading and checkpoint saving.

Observations:

- All 8 conditions ran 20 steps without out-of-memory errors at 4,096 tokens. The full run later ran out of memory
  at step 21 (§4): the longest examples come later in the shuffled order.
- Step time is 111–143 s on a T4, which is about **150–180 training tokens/s**. The plan assumed 500–1,500 tok/s
  (architecture §9.2), so training is 3–10× slower than planned. The data is also 2.5× larger than planned (3,000
  examples instead of ~1,200). B5 and `b5_no_esc` are the slowest conditions; B5 has the longest examples.
- **2 epochs (12–15 h per model) do not fit in a 12 h Kaggle session**, and all 8 at 2 epochs would take about
  100 GPU-hours. The config now uses 1 epoch (5.8–7.4 h per model), so B4 and B5 can train in parallel in one
  session.
- `b5_no_inter` has the highest loss and a 2–3× larger gradient norm (0.48 / 0.78 vs ~0.17 / ~0.29). Without the
  intermediate fields, the decision token is the first and hardest target token.
- The loss values come from a 20-step run whose cosine schedule decayed to ~0 by step 20. They show that training
  runs and the loss falls, **not** how good the gates are.

## 4. Full training run: B4 and B5 (`runs/nb03_v3`)

### First attempt failed (`runs/nb03_v2`, 2026-10-28 21:11–22:01)

1. **CUDA out of memory at step 21–22 on both GPUs.** Both conditions see the examples in the same shuffled order,
   so both hit the same ~3.8k-token example at the same step. The backward pass needed ~0.6 GB more than a T4 has.
   The 20-step timing run stopped just before this example.
2. **Stale code.** Kaggle reported the new code upload as ready while it was still processing, so the run used
   `f558cd5` (2 epochs, 376 steps) instead of the 1-epoch config. Since then, every push is preceded by downloading
   `GIT_SHA` from the Kaggle dataset and checking that it matches.

**Fix:** `train.max_length` 4,096 → **2,560** (commit `73cc6a4`). Examples longer than this are dropped, not
truncated, and the dropped ids are recorded in `train_summary.json`.

### Result (2026-10-28 22:13 → 2026-10-29 04:14, code `73cc6a4`)

| | B5 `b5_qlora_4way` | B4 `b4_qlora_binary` |
|---|---|---|
| Optimizer steps | 187 / 187 (1 epoch) | 187 / 187 (1 epoch) |
| Examples kept / dropped (> 2,560 tokens) | 2,985 / **15** (0.5%) | 2,992 / **8** (0.3%) |
| Median / max tokens before the cut | 1,244 / 3,825 | 1,168.5 / 3,751 |
| Training tokens | 3,919,312 | 3,714,636 |
| Training time | 21,043 s (5 h 51 min), 112.5 s/step | 20,953 s (5 h 49 min), 112.0 s/step |
| Mean training loss | 0.0473 | 0.0493 |
| Adapter size | 167 MB | 167 MB |

All dropped examples are generated variants, mostly workspace `user_task_19` (long e-mail and file contexts);
none is a hand-authored synthetic case. The 8 B4 drops are a subset of the 15 B5 drops (B4's target is shorter).

**Loss curve** (every 10 steps):

| Step | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 | 100 | 110 | 120 | 130 | 140 | 150 | 160 | 170 | 180 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B5 | 0.440 | 0.069 | 0.051 | 0.053 | 0.035 | 0.036 | 0.029 | 0.027 | 0.010 | 0.024 | 0.017 | 0.016 | 0.009 | 0.010 | 0.018 | 0.011 | 0.010 | 0.016 |
| B4 | 0.386 | 0.084 | 0.078 | 0.049 | 0.032 | 0.035 | 0.027 | 0.025 | 0.029 | 0.028 | 0.021 | 0.021 | 0.018 | 0.019 | 0.024 | 0.013 | 0.013 | 0.013 |

The loss falls within the first 20 steps and then flattens out at 0.01–0.02. A low loss is expected: the target
is a short JSON object whose fields are mostly predictable from the evidence. It says nothing about
generalisation; the NB04 test results do ([04_learned_gates.md](04_learned_gates.md)).

## Takeaways for the report

- Deviations from the proposal: **1 epoch instead of 2** (measured T4 cost) and **max length 2,560 instead of
  4,096** (T4 memory; drops 15 / 8 of 3,000 examples). Report both.
- B4 and B5 see exactly the same 3,000 examples. They differ only in label space (and the resolution loop at
  inference), which keeps the H2 comparison (B4 vs B5) clean.
- The training labels are not two-annotator human labels: the 1,000 variants are rule-labelled, and the 2,000
  synthetic cases are author-labelled and reviewed by Claude. A teammate still has to spot-check them.
