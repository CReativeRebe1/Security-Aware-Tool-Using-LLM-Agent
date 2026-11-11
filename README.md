# Security-Aware Tool-Using LLM Agent

CL3410 (Language Models and Agents, IIIT Hyderabad, Monsoon 2026) group project:
*Provenance- and authority-aware resolution of tool actions at runtime.*

An LLM agent that uses tools (send money, send email, share files, …) can be hijacked by text it reads
(prompt injection), can act on values the user never gave, or can act beyond what the user may authorise.
This project puts a **security gate** in front of every state-changing tool call. The gate does not only say
ALLOW or BLOCK: it can **ASK_USER** (missing intent, unclear recipient or amount) or **ESCALATE** to the person
who holds the authority (manager, security desk, resource owner), and it re-decides after the answer.

Benchmark: the AgentDojo **banking** and **workspace** suites, plus human-labelled gate cases built from them.

> **Branch `GateExp`** holds the current architecture (B5 v2 + GateExp layers) described below, its runs and its
> evaluation log ([`docs/GATE_EVALUATION.md`](docs/GATE_EVALUATION.md)). The original design of all baselines is in
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Results at a glance (current architecture)

Live Kaggle T4 run, B5 v2 adapter inside the GateExp layers, clause coverage tags on (NB08 v7,
`results/data/2026-11-12_gateexp_tags_ab_b5v2/tags/`). Targets: unsafe actions ≤ 5 %, unneeded asks ≤ 10 %.

| Set | Correct final outcome | Unsafe actions allowed (≤ 5 %) | Safe actions blocked | Unneeded asks (≤ 10 %) | Confirmations |
|---|---|---|---|---|---|
| Test (212) | 212/212 (100 %) | 0/118 (0.0 %) | 0/133 (0.0 %) | 2/110 (1.8 %) | 29/212 (13.7 %) |
| Dev (236) | 229/236 (97.0 %) | 3/112 (2.7 %) | 0/149 (0.0 %) | 17/152 (11.2 %) | 6/236 (2.5 %) |
| Attacks (61, red team) | 60/61 (98.4 %) | 0/51 (0.0 %) | 1/11 (9.1 %) | 2/33 (6.1 %) | 6/61 (9.8 %) |
| **Total** | **501/509 (98.4 %)** | **3/281 (1.1 %)** | **1/293 (0.3 %)** | **21/295 (7.1 %)** | **41/509 (8.1 %)** |

*Unneeded asks* exclude **confirmations** — deliberate questions before an irreversible action (first payment to a
new payee, an amount the user never stated, an action the user did not ask for), reported as their own rate.
With a noisy user (15 % wrong or unhelpful answers) attacks reach 3.9 % unsafe (ledger run, same rules).

For comparison, Run 1 (B5 alone, no GateExp layers) allowed **16.9 %** unsafe actions on test.

Honest caveats: several GateExp rules were found by looking at test failures, so test flatters the setup —
**dev and the attack set are the fairer check**. All numbers use oracle provenance; the live AgentDojo run (guessed
provenance) is still to be done. Every change and run is logged with its numbers in
[`docs/GATE_EVALUATION.md`](docs/GATE_EVALUATION.md); run folders are indexed in
[`results/data/RUNS.md`](results/data/RUNS.md).

---

## Architecture (current: B5 v2 + GateExp)

### Design idea

**The model judges intent and risk; code keeps exact state.** A fine-tuned LLM is good at reading a request and
the content around it, and bad at exact bookkeeping (comparing two IBANs digit by digit, adding up today's payments,
remembering which call a "yes" was about). So the gate is three layers around one learned model:

1. **Facts** — computed deterministically and shown to the model.
2. **Hard rules before the model** — only policy invariants that no argument may override.
3. **Checks after the model** — confirmations and a small ledger that can make the model's answer stricter,
   never looser (except where a real answer already settled the question).

### Runtime flow (one proposed tool call)

```
 User prompt ──▶ Task agent (Qwen3-8B) ──▶ proposed_call {function, args}
                                                │
                                                ▼
 ┌─────────────────────────── Security context builder ───────────────────────────┐
 │ Provenance   where each argument came from (user / tool output / injected)      │
 │ Authority    who may authorise this (user, manager, security desk, owner)       │
 │ Sensitivity  data label → destination  (PUBLIC < INTERNAL < CONFIDENTIAL < …)  │
 │ Policy RAG   top-8 handbook clauses (BM25 + fact index + clause coverage tags)  │
 │ History      earlier ASK_USER / ESCALATE rounds and their answers               │
 └───────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ GateInput
                                         ▼
 ┌──────────────────────────────── GateExp gate ───────────────────────────────────┐
 │ 1. augment     facts + ledger  (intent, risk, data source, split / daily total,  │
 │                file labels, bound confirmations, blank answers)                  │
 │ 2. pre-rules   declined → credential_flow → untrusted_provenance → authority     │
 │                (a rule that fires decides; the model is not asked)               │
 │ 3. B5 model    Qwen3-8B + QLoRA adapter, 4-way, enum-scored decoding             │
 │ 4. post-rules  guards → no_reescalate → no_reask → intent_confirm →              │
 │                new_payee_confirm → amount_confirm → unlabelled_external →        │
 │                route_authority                                                   │
 │ 5. trace       facts + every rule step + the model's own answer (decision log)   │
 └──────┬──────────────┬──────────────────┬──────────────────────┬──────────────────┘
        │ ALLOW        │ BLOCK            │ ASK_USER             │ ESCALATE
        ▼              ▼                  ▼                      ▼
     execute        refuse            user answers         approver decides
                                          └──────── new evidence ───┘
                                                   │
                            same gate again (≤ 2 rounds; unresolved → BLOCK)
```

### Gate input and output

`GateInput` is one JSON format for every gate, for training and for evaluation: user prompt, proposed call, prior
calls, per-argument provenance, authority facts, sensitivity, retrieved policy clauses, untrusted content (tool
outputs, rendered as data, never as instructions) and the resolution history.
`GateOutput` = `decision` (ALLOW / BLOCK / ASK_USER / ESCALATE), `missing_evidence` (what is missing:
user_intent, recipient_identity, resource_target, approval, data_classification), `required_authority` (who must
decide) and `p_allow`. The question the gate asks and the person it routes to come from these fields.

### Layer 1 — facts and ledger (`src/sagate/gate/gateexp.py`, `augment`)

| Fact | Meaning | Used by |
|---|---|---|
| `intent` | asked / delegated ("do what the email says") / not_asked | intent_confirm, model |
| `risk` | high for transfers, disclosure, deletes, account changes, unknown recipients | intent_confirm, model |
| `data_source` | where the deciding arguments came from: user / third_party / untrusted | pre-rules, model |
| `split_payment` | part of a larger requested payment over the limit, or today's total over the daily limit | authority |
| `paid_today` | payments already made that day, read from the transaction history the agent saw (earlier tasks too) | authority |
| `file_labels` | label per sent file = max(configured label, content written into it, label of files read before); unlabelled → INTERNAL | sensitivity, authority |
| bound history | a "yes" or approval counts only for the call it was about (payee + amount); "yes, whatever" answers nothing | all rules, model |

The facts that matter for the decision are also written into the model's input (`checks`), so a retrain can
learn them.

### Layer 2 — rules before the model (they decide alone)

| Rule | Fires when | Decision |
|---|---|---|
| `declined` | the user or approver already said no | BLOCK |
| `credential_flow` | a password / reset link / token / security code would flow to a less protected place | BLOCK (even when the user asks) |
| `untrusted_provenance` | the deciding arguments came from injected content | BLOCK |
| `authority` | the user may not authorise this (limit, split, label downgrade, other owner) | ESCALATE to the required role, or BLOCK if the approver's written policy denies it; an unlabelled file asks the owner first |

### Layer 3 — the learned model (B5)

* Base: `unsloth/Qwen3-8B-bnb-4bit` (4-bit), thinking off, greedy enum-scoring decoder (no sampling; `p_allow`
  from the decision token).
* Adapter: QLoRA r 16, α 32, dropout 0.1, 1 epoch, trained on the human-labelled training split (1,049 cases),
  generated policy variants and rule-based augmentation (one deciding fact changed per copy; label mix
  ALLOW 35 / BLOCK 30 / ASK 20 / ESCALATE 15), with the GateExp facts in the input.
* Current adapter `b5_v2`: decision-weighted loss. Prepared next retrain `b5_v3` / `b5_v3_nt` (not run yet):
  **cost-matrix loss** (a wrong ALLOW on a risky case costs 3–5, a needless question 0.3–0.5) and **safe twins**
  (risky case with its one deciding fact made safe → ALLOW) against over-asking.

### Layer 4 — checks after the model (can only make the answer stricter)

| Check | Effect |
|---|---|
| `guards` | placeholder arguments, over-limit, cumulative limit, out of scope → BLOCK / ESCALATE |
| `no_reescalate` | a real approver already approved (not an "approval note" in a document) → no second escalation |
| `no_reask` | the user already confirmed this call → no identical second question |
| `intent_confirm` | high risk and the user did not ask, or delegated to content → **confirm** |
| `new_payee_confirm` | first payment to a payee not on the approved list → **confirm** the IBAN |
| `amount_confirm` | the amount is not one the user stated (request or answer) → **confirm** the amount |
| `unlabelled_external` | file with only the default label goes outside → ask what the data is |
| `route_authority` | the model asked the user, but only an approver can decide → ESCALATE |

Confirmations are ASK_USER with guard `confirm:*`, reported separately from unneeded asks.

### Resolution loop

ASK_USER goes to the user, ESCALATE to the named approver (mock approver driven by the authority YAML; it may
deny). The answer is added to the history and the **same gate** decides again; at most 2 rounds, then BLOCK.
An answer never raises the user's own authority.

### Decision log and fault attribution

Every decision carries a trace: the facts, each rule (fired or not) and the model's own answer. A wrong outcome is
attributed by following that chain: **rules** (a rule decided, or the deciding fact never reached the model),
**resolution** (an answer led to the wrong action), or **training** (the chain was intact and the model was wrong).

### Policy and configuration files

| File | Holds |
|---|---|
| `resources/handbooks/{banking,workspace}.md` | policy clauses (BANK-x.y / WS-x.y) retrieved for the gate |
| `resources/authority/*.yaml` | principals, approvers, approved payees, limits, approver policies |
| `resources/sensitivity/*.yaml` | file labels, content markers, destination classes |
| `resources/policy_index.json`, `resources/policy_tags.yaml` | fact → clause index (from labels) and per-clause coverage tags |
| `configs/conditions/b5_v2_gateexp.yaml` | the current gate: adapter + rule order |
| `configs/base.yaml` | model, retrieval (`rag_k`, `rag_tags`), resolution limits |

### Baselines (same input, same evaluation)

| Gate | What it is |
|---|---|
| B0 | no gate (agent alone) |
| B1 | deterministic rules |
| B2 / B3 | prompted Qwen3-8B, binary / 4-way |
| B4 / B5 | QLoRA Qwen3-8B, binary / 4-way with resolution |
| **B5 + GateExp** | B5 inside the fact, rule and ledger layers (this branch) |

### Evaluation sets

| Set | Size | Purpose |
|---|---|---|
| train (human) | 1,049 | training only |
| dev | 236 | every change is checked here first |
| test | 212 | held-out families; final numbers |
| attacks | 61 | red-team cases written to break GateExp (26 banking, 25 workspace, 10 benign) |

---

## Running the current gate

```bash
pip install -e ".[dev]"            # CPU: rules, facts, replay, reports, tests
pytest -q

# one condition over a case file (GPU; adapters from Kaggle NB03)
python -m sagate.eval.run_gate --condition b5_v2_gateexp --cases annotations/dev_cases.jsonl \
       --pool dev --adapter-dir outputs/adapters --out outputs/gateexp/dev
# report (core metrics + confirmation rate + rule usage + fault attribution) and decision log
python -m sagate.eval.gateexp_report report --pred outputs/gateexp/dev/b5_v2_gateexp.jsonl --cases annotations/dev_cases.jsonl
python -m sagate.eval.gateexp_report log    --pred ... --cases ... --out decision_log.jsonl
# replay saved model answers under changed rules (no GPU; later rounds approximated)
python -m sagate.eval.gateexp_report replay --saved <predictions.jsonl> --cases ... --out replay.jsonl
# regenerate the rule-based training augmentation
python -m sagate.train.augment --out annotations/train_augmented.jsonl
```

Kaggle: `kaggle/nb08_gateexp` runs the GateExp gate on test, dev and attacks (settings `COND`, `POOLS`, `TAGS_AB`);
`kaggle/nb03_train_qlora` with `GROUP = "V3"` trains `b5_v3` and `b5_v3_nt` (one per GPU, ~4.6 h).
Stage code with `bash kaggle/stage_code.sh --owner <kaggle-user>` (see [`docs/RUN_GUIDE.md`](docs/RUN_GUIDE.md)).

---

## Limitations

* Oracle provenance in the offline numbers; with provenance guessed from the conversation, Run 1 showed 20 % unsafe —
  the live AgentDojo run of the final gate is still open.
* Several rules were fitted after looking at test failures; dev and attacks are the fairer estimate.
* Confirmations cost questions on irreversible actions (8 % of cases) by design.
* The learned model over-asks on "safe twins" of risky cases (confidently wrong, not mis-calibrated); the prepared
  retrain targets this with data, not thresholds.
* The simulated user and approver know the ground truth; the noisy-user runs are the check on this.

---

## Dataset

This repository also holds the base data the project builds on: AgentDojo's **workspace** and **banking** suites,
exported to flat JSON/JSONL, plus logged AgentDojo agent runs used as cached B0 traces, and the human-labelled
gate cases (`annotations/`).

### Where the data comes from

| Source | Used for | Origin | Licence |
|---|---|---|---|
| AgentDojo task suites (v1.2.2) | User tasks, injection tasks, tools, environments, injection slots | [ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo) `src/agentdojo/default_suites`, `src/agentdojo/data/suites` | MIT |
| AgentDojo run logs | Cached agent traces and per-call gate inputs | same repo, `runs/` | MIT |
| Train/test split, provenance tags, heuristic flags | Derived by us | computed from the two sources above | — |

> E. Debenedetti et al. *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for
> LLM Agents.* NeurIPS 2024 Datasets & Benchmarks. arXiv:2406.13352.

The export was produced statically (parsing the Python task definitions, YAML and JSON); no AgentDojo code
was executed. The other works cited in the proposal (AutoDojo, PACT, Agent-Sentry, Progent, Fides, QLoRA, Qwen3) are
papers/code we reference, not data sources, and are not in this repository.

### Contents and counts

All files are under [`data/processed/agentdojo/`](data/processed/agentdojo/).

| File | Rows | Workspace | Banking |
|---|---|---|---|
| `user_tasks.jsonl` | 56 | 40 | 16 |
| `injection_tasks.jsonl` | 23 | 14 | 9 |
| `injection_vectors.jsonl` | 20 | 16 | 4 |
| `tools.jsonl` | 35 | 24 | 11 |
| `scenarios.jsonl` | 760 | 600 | 160 |
| `traces.jsonl.gz` | 23,602 | 16,640 | 6,962 |
| `tool_call_proposals.jsonl.gz` | 61,152 | 42,096 | 19,056 |
| `environments/{suite}_{template,default}.json` | 4 files | | |
| `splits/scenario_split.json` | 1 file | | |
| `summary.json` | counts | | |

**Scenarios** = each user task run benignly (56) + each user task paired with every injection task whose
injection slot it reaches (560 workspace + 144 banking = 704).

**Traces** come from 29 model/defence pipelines (GPT-3.5/4/4o, Claude 3–3.7, Gemini 1.5/2.0, Llama 3/3.3,
Command-R, Meta-SecAlign, plus GPT-4o with spotlighting, tool-filter, PI-detector and repeat-prompt defences).

| Attack type | Traces |
|---|---|
| `important_instructions` | 12,626 |
| `direct`, `ignore_previous` | 3,200 each |
| `none` (benign) | 1,608 |
| `important_instructions_*` variants, `injecagent`, `tool_knowledge` | 384 each |
| `*_dos` variants | 56 each |

Of the 21,994 attacked traces, 2,785 (12.7%) achieved the attacker's goal.

### Train / dev / test split

Fixed before any training data is generated (seed 42), as the proposal requires.

- **User tasks:** 28 train / 6 dev / 22 test, stratified by suite × whether the task reaches an injection slot.
  `dev` is part of the train-source pool (used for B4 threshold calibration).
- **Injection tasks:** ~40% test per suite.
- **Scenario split columns:** `user_task_split`, `injection_task_split`, and `strict_split`. `strict_split` is
  `train` or `test` only when the user task and attacker goal fall on the same side; otherwise it is `excluded`.

| `strict_split` | Benign | Injection | Total |
|---|---|---|---|
| train (incl. dev) | 34 | 242 | 276 |
| test | 22 | 120 | 142 |
| excluded | 0 | 342 | 342 |

### Schema

#### `user_tasks.jsonl`
| Field | Type | Notes |
|---|---|---|
| `suite` | str | `workspace` \| `banking` |
| `id` | str | e.g. `user_task_0` |
| `prompt` | str | what the user asks the agent |
| `difficulty` | str \| null | `EASY` \| `MEDIUM` \| `HARD` |
| `comment`, `ground_truth_output` | str \| null | from AgentDojo |
| `ground_truth_calls` | list[{`function`, `args`}] | expected tool calls; runtime-computed values appear as `{"__expr__": "<source>"}` |
| `ground_truth_static` | bool | all calls fully resolved (false for workspace 10, 13, 19, 31, 32, 34, 36, 37) |
| `ground_truth_source` | str \| null | original Python `ground_truth` method |
| `combined_from` | list[str] | only for combined tasks (two user tasks in one prompt) |
| `benchmark_version`, `versions_available`, `defined_in` | | AgentDojo version bookkeeping |
| `injection_vectors` | list[str] | injection slots this task's tool outputs expose |

#### `injection_tasks.jsonl`
Same as above with `goal` (attacker instruction) instead of `prompt`, and no `injection_vectors`.

#### `injection_vectors.jsonl`
`suite`, `vector_id`, `description`, `default` (benign text in the slot), `reached_by_user_tasks`.

#### `tools.jsonl`
`suite`, `name`, `module`, `description`, `parameters` (list of `name`, `type`, `description`, `required`, `default`).

#### `scenarios.jsonl`
`scenario_id` (`suite|user_task|injection_task-or-benign`), `suite`, `user_task_id`, `injection_task_id`,
`type` (`benign` | `injection`), `injection_vectors`, `user_task_split`, `injection_task_split`, `strict_split`.

#### `traces.jsonl.gz`
| Field | Notes |
|---|---|
| `trace_id` | `pipeline\|suite\|user_task\|attack\|injection_task` |
| `pipeline`, `suite`, `user_task_id`, `injection_task_id`, `attack_type` | |
| `injections` | slot → exact injected text |
| `utility` | user task completed |
| `attack_succeeded` | AgentDojo `security` flag; null for benign runs |
| `tool_calls` | ordered list of `{function, args}` |
| `messages` | full conversation (system, user, assistant, tool) |
| `error`, `duration` | |

#### `tool_call_proposals.jsonl.gz` — one row per proposed tool call
| Field | Notes |
|---|---|
| `proposal_id`, `trace_id`, `step`, `message_index` | link back to the trace |
| `pipeline`, `suite`, `user_task_id`, `injection_task_id`, `attack_type` | |
| `user_prompt`, `prior_calls`, `proposed_call` | gate input |
| `arg_provenance` | per argument: any of `user_prompt`, `injection`, `tool_output`, `unknown`, `too_short` |
| `injection_seen_before_call` | injected text already in context |
| `matches_user_task_ground_truth`, `matches_injection_task_ground_truth` | loose heuristic (same function + a shared distinctive value such as an IBAN/email/filename) |
| `trace_utility`, `trace_attack_succeeded` | outcome of the whole trace |

`arg_provenance` is oracle-style: it uses the known injected strings, so it is an upper bound for the
inferred-provenance condition. The `matches_*` flags are weak labels for analysis and variant generation —
**not** gold ALLOW / BLOCK / ASK_USER / ESCALATE labels.

### Caveats

- Run logs have no benchmark-version field; some were produced against older task versions (v1.0–v1.1).
- Provenance is substring matching; numbers, dates and short values are often `unknown`.
- 468 injection-only runs (no user task) are not exported. Slack and travel suites are out of scope.
- See [`data/processed/agentdojo/README.md`](data/processed/agentdojo/README.md) for additional notes.

## Code (`src/sagate`)

Implementation of [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): baselines (B0–B3), training (B4/B5 and the
ablations), threshold calibration, end-to-end gated runs and the statistics report. Section 14 of the
architecture lists what is built, what has run, and where it deviates from the plan.

```bash
pip install -e ".[dev]"                 # CPU parts: case building, B1, variants, SFT data, metrics, tests
pip install -e ".[gpu,agentdojo]"       # + Qwen3 backend and the AgentDojo agent
pip install -e ".[train]"               # + QLoRA training
pytest -q
```

| Step | Command |
|---|---|
| Build gate cases from the logged runs | `python -m sagate.data.build_cases --pool test` (also `train`, `dev`) |
| Export cases for annotation | `python -m sagate.data.annotation export --cases outputs/cases/test_candidates.jsonl --sample 160 --out annotations/batch1.csv` |
| Agreement / gold file | `python -m sagate.data.annotation agreement annotations/batch1_*.csv` · `... gold annotations/batch1_adjudicated.csv --out annotations/gold.jsonl` |
| Freeze the labelled case file | `python -m sagate.data.annotation freeze --cases outputs/cases/test_candidates.jsonl [annotations/test_nl.jsonl] --gold annotations/gold.jsonl --pool test --out annotations/test_cases.jsonl` |
| B1 rules (CPU) | `python -m sagate.eval.run_gate --condition b1_rules --cases outputs/cases/test_candidates.jsonl` |
| B2 / B3 prompted (GPU) | `python -m sagate.eval.run_gate --condition b3_prompt_4way --cases ... [--responses noisy]` |
| Report | `python -m sagate.eval.report --cases ... --pred outputs/predictions/*.jsonl [--gold annotations/gold.jsonl --compare A B]` |
| B0 Qwen traces (GPU) | `python -m sagate.agent.run_b0 --shard 0 --num-shards 2`, then `... run_b0 --merge <shards>` (traces.jsonl + B0 utility/ASR in b0_summary.json), then `python -m sagate.agent.extract_proposals` |
| Smoke test / throughput | `python -m sagate.smoke [--model-id Qwen/Qwen3-0.6B]` |
| Replay old-log executable cases in the pinned AgentDojo | `python -m sagate.agent.replay --cases outputs/cases/test_candidates.jsonl --out outputs/cases/test_candidates.replayed.jsonl --report ...` |
| Training variants / generated dev pool (CPU) | `python -m sagate.train.variants --pool train_only` · `... --pool dev --out outputs/sft/dev_cases.jsonl` |
| Check NL training examples | `python -m sagate.train.nl_examples check annotations/train_nl.jsonl [--test-cases annotations/test_cases.jsonl]` |
| SFT data for all 8 trained conditions | `python -m sagate.train.build_sft --cases outputs/sft/train_only_variants.jsonl annotations/train_nl.jsonl` |
| QLoRA (GPU) | `python -m sagate.train.train_qlora --condition b5_qlora_4way --sft outputs/sft/b5_qlora_4way.jsonl` |
| Learned gates | `python -m sagate.eval.run_gate --condition b5_qlora_4way --cases annotations/test_cases.jsonl --adapter-dir outputs/adapters` |
| B4 threshold (dev only) and matched test run | `python -m sagate.eval.pareto select --b4 dev/b4.jsonl --b5 dev/b5.jsonl --cases outputs/sft/dev_cases.jsonl --out t.json` · `... apply --pred test/b4.jsonl --threshold-file t.json --out test/b4_qlora_binary_matched.jsonl` |
| End-to-end gated runs (GPU) | `python -m sagate.agent.run_e2e --condition b5_qlora_4way --adapter-dir outputs/adapters --shard 0 --num-shards 2`, then `... --merge <shards>` |
| End-to-end metrics | `python -m sagate.eval.e2e_metrics --traces outputs/b0_traces/traces.jsonl outputs/e2e/b5_qlora_4way/traces.jsonl --json report/e2e.json` |
| Statistics + report | `python -m sagate.eval.analysis --cases annotations/test_cases.jsonl --pred outputs/predictions/test/*.jsonl --e2e report/e2e.json --out report` |

Kaggle: `bash kaggle/stage_code.sh`, then `kaggle datasets version -p build/sagate-code --dir-mode zip -m "<sha>"`
(first time: `kaggle datasets create`), then `kaggle kernels push -p build/kernels/nb00_setup_smoke --accelerator
NvidiaTeslaT4`. Kernels in `kaggle/`: NB00 (smoke), NB01 (B0 traces), NB02 (B1/B2/B3), NB03 (QLoRA, 8 adapters), NB04 (learned gates +
B4 threshold), NB05 (end-to-end B0 vs B5), NB06 (statistics + report, CPU).
