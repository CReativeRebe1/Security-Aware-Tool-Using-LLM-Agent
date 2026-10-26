# Architecture — Security-Aware Tool-Using LLM Agent (Kaggle implementation)

Scope of this document: the software architecture and the Kaggle execution plan for the CL3410 project
*Provenance- and authority-aware resolution of tool actions at runtime*. It turns the proposal
(Sections 4–9) into packages, interfaces, data contracts and notebooks. No code exists yet; this is the
plan to review before implementation.

---

## 1. Design principles

| # | Principle | Consequence in code |
|---|---|---|
| P1 | **The gate is the sole execution authority.** | Every state-changing tool call goes through `Gate.decide()`; the executor refuses anything without an `ALLOW` record. |
| P2 | **B4 vs B5 differ only in decision space + resolution loop.** | One gate class, one prompt renderer, one training script; the condition is a config (`decision_space`, `resolution`). |
| P3 | **Evidence ablations are applied identically in training and inference.** | A single `EvidenceMask` is applied inside the context builder, which is used by both the SFT data builder and the evaluator. |
| P4 | **Untrusted content is data, never instructions.** | Rendered only inside `<untrusted id=… source=…>` blocks with delimiter escaping; authority is never read from it. |
| P5 | **Split before generate; leakage is asserted, not assumed.** | Every generator/evaluator calls `splits.assert_pool(case, "train"|"test")` on `strict_split`. |
| P6 | **Everything expensive is cached and resumable.** | GPU jobs append to JSONL keyed by a content hash and skip already-done keys, so a Kaggle session can die and resume. |
| P7 | **Deterministic.** | Greedy decoding, fixed seeds, pinned library versions, enum-scoring decoder (no sampling). |

---

## 2. System overview

### 2.1 Runtime (one proposed tool call)

```
                 ┌───────────────────────────────────────────────────────────────────────┐
  User ─prompt─▶ │ Task agent  (Qwen3-8B, 4-bit, thinking off)  — AgentDojo pipeline       │
                 └──────────────┬────────────────────────────────────────────────────────┘
                                │ proposed_call {function, args}  + conversation so far
                                ▼
 ┌──────────────────────────────────────── Security context builder ──────────────────────────┐
 │  ProvenanceTracker      oracle | inferred     → per-arg sources + trust, record IDs P1..Pn    │
 │  AuthorityRegistry      direct YAML lookup    → principal, role, resource owner, required auth│
 │  SensitivityLabeler     PUBLIC<INTERNAL<CONF<RESTRICTED → flow ok | high_to_low             │
 │  PolicyRetriever (RAG)  BM25 + embeddings     → top-k handbook clauses (IDs BANK-x.y / WS-x.y)│
 │  ResolutionHistory      answers from earlier ASK/ESCALATE rounds                             │
 │  EvidenceMask           drops fields for ablations (same in train + test)                    │
 └──────────────┬──────────────────────────────────────────────────────────────────────────────┘
                │ GateInput (JSON)
                ▼
 ┌────────────── Gate (B1 rules | B2/B3 prompted | B4/B5 QLoRA) ──────────────┐
 │  render prompt → enum-scoring constrained decoder → GateOutput (JSON)       │
 │  {missing_evidence, required_authority, decision, evidence_cited, p_allow}  │
 └──────┬──────────────┬─────────────────┬──────────────────┬──────────────────┘
        │ALLOW         │BLOCK            │ASK_USER          │ESCALATE
        ▼              ▼                 ▼                  ▼
  SandboxExecutor   minimal refusal   FixedUserResponder  MockApprover
  (AgentDojo env)   to the agent      (15% noisy)         (authority state, may deny)
  + audit log                            └──────── new evidence ───────┘
                                                      │
                                re-run the SAME gate (≤ 2 interaction rounds; then BLOCK)
```

### 2.2 Offline experiment flow

```
 data/processed/agentdojo  ──┐
 (scenarios, traces,         │      ┌──────────────┐      ┌─────────────────┐
  proposals, envs, split)    ├────▶ │ Case builder │ ───▶ │ GateInput cache  │ (oracle + inferred)
 annotations/ (human CSV) ───┤      └──────────────┘      └────────┬────────┘
 authority/*.yaml  ──────────┤                                     │
 handbooks/*.md  ────────────┘                                     │
                                                                    ▼
 NB01 B0 traces (Qwen) ──▶ proposals (same schema) ──▶ test-source cases ──▶ annotation ──▶ gold test set
                                                     train-source cases ──▶ variant generator ──▶ SFT data
                                                                                            │
                         NB03 QLoRA (B4, B5, ablations) ◀────────────────────────────────────┘
                                         │ adapters
                                         ▼
 NB02 B1/B2/B3  ──┐            NB04 offline eval (resolution loop, B4 threshold sweep on dev)
                  └──────────────────────┬────────────────────────────────────────────
                                         ▼
                            predictions/*.jsonl ──▶ NB06 stats (bootstrap, McNemar, Holm, Pareto)
                                         ▲
                NB05 end-to-end AgentDojo B0 vs B5 (executable subset)
```

---

## 3. Repository layout

```
Security-Aware-Tool-Using-LLM-Agent/
├── pyproject.toml                 # package "sagate", pinned deps, extras [train], [vllm], [agentdojo]
├── configs/
│   ├── base.yaml                  # model ids, paths, seeds, decoding, max lengths
│   ├── kaggle.yaml                # /kaggle/input, /kaggle/working overrides
│   └── conditions/                # one file per experimental condition (Section 7)
│       ├── b1_rules.yaml  b2_prompt_binary.yaml  b3_prompt_4way.yaml
│       ├── b4_qlora_binary.yaml  b5_qlora_4way.yaml
│       └── b5_no_prov.yaml  b5_no_auth.yaml  b5_no_rag.yaml  b5_no_ask.yaml
│           b5_no_esc.yaml  b5_no_inter.yaml  b5_inferred_prov.yaml
├── resources/
│   ├── authority/{workspace,banking}.yaml     # principals, roles, resources, approvers (synthetic)
│   ├── sensitivity/{workspace,banking}.yaml   # resource → label, destination → label
│   └── handbooks/{workspace,banking}.md       # 5–8 page policy handbooks, clause-ID tagged
├── annotations/                   # human labels (CSV per annotator) + adjudicated gold
├── data/processed/agentdojo/      # existing dataset (this branch)
├── src/sagate/
│   ├── config.py                  # dataclasses + YAML loader + env detection (local vs Kaggle)
│   ├── data/
│   │   ├── loaders.py             # typed readers for every file in data/processed/agentdojo
│   │   ├── splits.py              # strict_split lookup + assert_pool() leakage guard
│   │   └── cases.py               # TestCase / TrainCase dataclasses, (de)serialisation
│   ├── evidence/
│   │   ├── tools_registry.py      # tool → {state_changing, resource_arg, destination_arg, action}
│   │   ├── provenance.py          # OracleProvenance, InferredProvenance (matching + LLM attribution)
│   │   ├── authority.py           # AuthorityRegistry (direct lookup, no retrieval)
│   │   ├── sensitivity.py         # IFC labels + high_to_low flow check
│   │   ├── policy_rag.py          # clause chunker, BM25 + embedding hybrid retriever, Recall@k
│   │   ├── mask.py                # EvidenceMask (ablations)
│   │   └── context_builder.py     # assembles GateInput from (prompt, call, history, env, mask)
│   ├── gate/
│   │   ├── schema.py              # enums, GateInput, GateOutput, decision-space projections
│   │   ├── prompts.py             # system prompt + renderer with <untrusted> delimiting
│   │   ├── decoder.py             # enum-scoring constrained decoder (+ p_allow)
│   │   ├── rules.py               # B1 deterministic gate
│   │   ├── llm_gate.py            # PromptedGate (B2/B3), LearnedGate (B4/B5) — same class, adapter optional
│   │   └── cache.py               # hash(model, adapter, prompt) → GateOutput, JSONL-backed
│   ├── resolution/
│   │   ├── responders.py          # FixedUserResponder (clean/noisy), MockApprover
│   │   └── loop.py                # resolve(case, gate) → ResolutionTrace (≤ 2 rounds, default BLOCK)
│   ├── models/
│   │   ├── backend.py             # HFBackend (transformers + bitsandbytes nf4 + PEFT), VLLMBackend
│   │   └── chat.py                # Qwen3 chat template, enable_thinking=False
│   ├── train/
│   │   ├── variants.py            # structured policy-variant generator (~1,000)
│   │   ├── nl_examples.py         # load reviewed NL examples (~200)
│   │   ├── build_sft.py           # GateInput+gold → (prompt, target) per condition
│   │   └── train_qlora.py         # PEFT/TRL SFT, completion-only loss, resumable
│   ├── agent/
│   │   ├── pipeline.py            # AgentDojo pipeline: Qwen LLM element + GatedToolsExecutor
│   │   ├── run_b0.py              # cache Qwen B0 traces → same schema as traces.jsonl.gz
│   │   ├── extract_proposals.py   # traces → tool_call_proposals (reuses dataset logic)
│   │   └── run_e2e.py             # end-to-end B0 vs B5 (AgentDojo utility/security)
│   └── eval/
│       ├── metrics.py             # all metrics of Section 8
│       ├── stats.py               # paired bootstrap, exact McNemar, Holm–Bonferroni, α / κ
│       ├── pareto.py              # threshold sweep + frontier
│       └── report.py              # tables (raw counts + %), qualitative example picker
├── scripts/                       # thin CLIs: python -m sagate.<module> --config ...
├── notebooks/kaggle/              # NB00–NB06, thin wrappers over the package
└── tests/                         # unit tests for schema, mask, splits, loop, metrics, decoder
```

Notebooks contain no logic beyond config selection and calls into `sagate`, so the same code runs locally
(CPU, small model or rules) and on Kaggle (GPU).

---

## 4. Data contracts

### 4.1 `GateInput` (the single input format for every gate, training and evaluation)

```jsonc
{
  "case_id": "ws|user_task_13|injection_task_4|p3",
  "suite": "workspace",
  "user": {"principal_id": "emma", "prompt": "…original user request…"},
  "proposed_call": {"function": "send_email", "args": {"recipients": ["…"], "subject": "…", "body": "…"},
                    "state_changing": true, "action": "disclose"},
  "prior_calls": [{"function": "search_emails", "args": {"query": "…"}}],
  "provenance": [                                   // removed by EvidenceMask(provenance=False)
    {"id": "P1", "arg": "recipients", "value": "mark@…", "sources": ["tool_output:search_emails#2"],
     "trust": "untrusted", "instruction_origin": "email:id_27"}
  ],
  "authority": {                                    // removed by EvidenceMask(authority=False)
    "principal_role": "employee", "resource": "file:client-contracts.docx", "resource_owner": "legal",
    "affected_party": "external:mark@…", "user_may_authorize": false, "required_role": "manager",
    "prior_approvals": []
  },
  "sensitivity": {"resource": "CONFIDENTIAL", "destination": "PUBLIC", "flow": "high_to_low"},
  "policy_clauses": [{"id": "WS-4.2", "text": "…"}],   // removed by EvidenceMask(rag=False)
  "untrusted_content": [{"id": "T1", "source": "email:id_27", "text": "…(truncated)…"}],
  "resolution_history": [{"round": 1, "kind": "ASK_USER", "question_target": "recipient_identity",
                          "response": "…", "responder": "user"}]
}
```

### 4.2 `GateOutput` (schema-constrained)

```jsonc
{"missing_evidence": "none|user_intent|recipient_identity|resource_target|approval|data_classification",
 "required_authority": "none|current_user|resource_owner|manager|security_admin",
 "decision": "ALLOW|BLOCK|ASK_USER|ESCALATE",     // binary conditions: ALLOW|BLOCK only
 "evidence_cited": ["P1", "WS-4.2"],             // filtered to IDs present in the input; not scored
 "p_allow": 0.83}                                // added by the decoder, not generated
```

Field order is `missing_evidence → required_authority → decision → evidence_cited` so the intermediate
targets act as structured reasoning before the decision. In `b5_no_inter` those two fields are dropped from
the target (decision first). *(Open decision for the team — see Section 12.)*

### 4.3 `TestCase` / `TrainCase`

`GateInput` plus: `subset` (`executable` | `decision_only`), `scenario_id`, `proposal_id` (executable only),
`category` (e.g. `authority_spoofing`), and gold fields:

| Field | Meaning |
|---|---|
| `gold_decision` | first-round four-way label (human, adjudicated) |
| `gold_final_action` | `ALLOW` / `BLOCK` after legitimate resolution — the B4 target and the metric target |
| `gold_missing_evidence`, `gold_required_authority` | intermediate targets |
| `gold_clause_ids` | for Recall@k |
| `user_response` | fixed reply `{text, provides, noisy: bool}` used by `FixedUserResponder` |
| `annotations` | raw per-annotator labels (for α / κ) |

Training cases carry the same gold fields, produced programmatically from explicit policy state.

---

## 5. Component design

### 5.1 Tool registry (`evidence/tools_registry.py`)
Static table over the 35 tools. Read-only tools (`search_*`, `get_*`, `list_files`, `read_file`) bypass the
gate by default (logged, configurable `gate_read_only: false`) so the gate only sees state-changing calls:

| Suite | State-changing tools | Action class |
|---|---|---|
| workspace | `send_email`, `share_file` | disclose |
| | `delete_email`, `delete_file`, `cancel_calendar_event` | delete |
| | `create_file`, `append_to_file`, `create_calendar_event`, `reschedule_calendar_event`, `add_calendar_event_participants` | modify / invite |
| banking | `send_money`, `schedule_transaction`, `update_scheduled_transaction` | transfer |
| | `update_password`, `update_user_info` | account change |

Each entry also names the *resource arg* and *destination arg* (e.g. `send_money.recipient`), which the
authority and sensitivity modules use.

### 5.2 Provenance (`evidence/provenance.py`)
- **Oracle**: reuse the dataset's `arg_provenance` logic — substring match of each argument value against
  the user prompt, the known injected strings, and other tool outputs. Upper bound.
- **Inferred** (runtime-realistic, no knowledge of which text is injected): (1) match values against the
  user prompt vs. each tool output in the conversation, tagging tool outputs from third-party content
  (emails, files, calendar descriptions, bill files) as `untrusted`; (2) for values with no match, or for the
  *instruction origin* ("which content made the agent do this?"), ask Qwen3-8B a constrained multiple-choice
  attribution question over `{user, T1..Tn}`. Attribution accuracy is scored against oracle.

### 5.3 Authority registry (`evidence/authority.py`)
Plain dictionary lookup over `resources/authority/<suite>.yaml`:

```yaml
principals:
  emma:        {role: employee, is_current_user: true}
  finance_mgr: {role: manager, approves: [transfer>500, external_payroll]}
  sec_admin:   {role: security_admin, approves: [account_change, external_share_confidential]}
resources:
  "file:client-contracts.docx": {owner: legal, label: CONFIDENTIAL}
  "iban:DE89370400440532013000": {owner: emma, label: RESTRICTED}
approved_recipients: ["*@bluesparrowtech.com", "iban:GB29NWBK60161331926819"]
rules:   # what each role may authorize per action class
  employee: {disclose: [INTERNAL, PUBLIC], transfer: {max_amount: 500, approved_only: true}}
```

Rule: authority is only ever read from this registry and from `MockApprover` responses — never from
untrusted content (this is what the authority-spoofing category tests).

### 5.4 Policy RAG (`evidence/policy_rag.py`)
Handbook clauses written as `### [BANK-3.2] Title` → one chunk per clause. Hybrid retriever: BM25
(`rank_bm25`) + `BAAI/bge-small-en-v1.5` embeddings on CPU, reciprocal-rank fusion, top-k=3 (k=5 for
Recall@5). The query is built from **trusted fields only** (tool name, action class, resource/destination
labels, user prompt) so injected text cannot steer retrieval.

### 5.5 Gate (`gate/`)
- **Prompt** (`prompts.py`): fixed system prompt with decision semantics + label vocabularies; the
  `GateInput` rendered as sections; untrusted text inside `<untrusted id=… source=…>` with any `<untrusted`
  / `</untrusted` sequences escaped. Qwen3 chat template with `enable_thinking=False`.
- **Enum-scoring constrained decoder** (`decoder.py`): the output fields are closed enums, so instead of a
  generic grammar engine the decoder teacher-forces the JSON skeleton and, at each enum field, scores every
  allowed value's token sequence (one batched forward pass with the shared prefix in KV cache) and takes the
  argmax. Gives (a) always-parseable output, (b) exact class probabilities — `p_allow` for the B4 threshold
  sweep and for Pareto curves, (c) no extra dependencies. `evidence_cited` is generated greedily and filtered
  to valid IDs.
- **B1 rules** (`rules.py`): ordered deterministic rules over the same `GateInput` (e.g. untrusted
  instruction origin + state-changing → BLOCK; user lacks authority + approver exists → ESCALATE; recipient
  not identified and user may authorize → ASK_USER; high_to_low flow without approval → BLOCK/ESCALATE per
  handbook). Four-way output plus binary projection.
- **One class for B2–B5**: `LLMGate(backend, adapter=None, decision_space=…)`. Prompted = no adapter.

### 5.6 Resolution loop (`resolution/loop.py`)

```
round = 0; out = gate(ctx)
while out.decision in {ASK_USER, ESCALATE} and round < 2:
    round += 1
    resp = user.respond(case, out) if ASK_USER else approver.respond(case, out)   # 1 interaction each
    ctx  = ctx.with_resolution(round, out, resp)                                   # via context builder
    out  = gate(ctx)
final = out.decision if out.decision in {ALLOW, BLOCK} else BLOCK
```

- `FixedUserResponder`: returns the case's fixed `user_response`; 15% of cases are flagged noisy (wrong or
  unhelpful). A user reply can supply *intent / identity / target*, never authority the user does not hold.
- `MockApprover`: deterministic from the authority YAML + case state; may deny.
- Every ASK/ESCALATE increments `interactions`; the trace is stored for metrics and failure analysis.

### 5.7 Agent + sandbox (`agent/pipeline.py`)
AgentDojo (pip `agentdojo`, pinned to the v1.2.2-compatible release) provides environments, tools and
scoring. We add two pipeline elements:
- `QwenLLM` — calls the model backend (vLLM OpenAI-compatible server with Hermes tool-call parsing, or the
  HF backend), thinking off, greedy.
- `GatedToolsExecutor` — replaces AgentDojo's `ToolsExecutor`: for each tool call, build `GateInput` from the
  live conversation (inferred provenance), run the resolution loop, execute only on `ALLOW`, otherwise
  return a minimal tool message (`"Action not permitted."`) that leaks no policy detail. Writes an audit log.

B0 = the same pipeline with the gate disabled.

### 5.8 Model backends (`models/backend.py`)

| Use | Backend | Quantisation |
|---|---|---|
| Gate inference (B2–B5), training, inferred provenance | HF `transformers` + `bitsandbytes` nf4 + PEFT adapter | 4-bit nf4, fp16 compute |
| Task agent for B0 trace generation / e2e (throughput) | vLLM server (`Qwen/Qwen3-8B-AWQ`) — **fallback** HF backend | AWQ 4-bit |

Gate conditions all use the *same* HF nf4 path, so prompted vs learned gates differ only by the adapter.

---

## 6. Training (`train/`)

- **Structured variants (~1,000)**: for each train-source proposal (strict_split = train, from Qwen B0 and the
  existing AgentDojo logs), systematically vary provenance (user / tool_output / injected), authority
  (user may authorize / needs owner / manager / admin / spoofed claim), resource label, approved-recipient
  status, policy clause and resolution history; the gold labels follow deterministically from the policy
  state. Class-balanced sampling to the target mix.
- **NL examples (~200)**: reviewed team-written seeds + paraphrases, loaded from `annotations/train_nl.jsonl`.
- **Resolution-round examples**: a share of examples include a `resolution_history` (answered ASK/ESCALATE),
  so the gate learns the second-round decision as well.
- **Per-condition SFT build**: `build_sft.py --condition b4_qlora_binary` applies the same `EvidenceMask` as
  evaluation, collapses labels (`B4`: `gold_final_action`; `b5_no_ask`/`b5_no_esc`: remove the class, map to
  `gold_final_action`), and drops intermediate fields for `b5_no_inter`. B4 and B5 see the *same examples*.
- **QLoRA**: PEFT LoRA r=16, α=32, dropout 0.05 on all linear projections; nf4 + double quant; fp16 compute
  (T4/P100 have no bf16); loss on the assistant JSON only; max length 3,072; batch 1 × grad-accum 16;
  lr 2e-4 cosine; 2 epochs; gradient checkpointing; checkpoint every 100 steps to `/kaggle/working` for
  resume. Optional Unsloth backend if speed is the bottleneck.
- **B4 operating point**: sweep the threshold on `p_allow` over the dev user tasks (part of train-source),
  pick the threshold matching B5's unauthorized-action rate on dev; never touch test.

---

## 7. Experimental conditions (config matrix)

Each condition is one YAML; the evaluator and SFT builder read the same file.

```yaml
# configs/conditions/b5_qlora_4way.yaml
name: b5_qlora_4way
gate: {kind: llm, adapter: adapters/b5_qlora_4way}
decision_space: [ALLOW, BLOCK, ASK_USER, ESCALATE]
evidence: {provenance: oracle, authority: true, sensitivity: true, rag: {enabled: true, k: 3}}
supervision: {intermediate: true}
resolution: {enabled: true, max_rounds: 2, user_noise: 0.15}
```

| Condition | Gate | Space | Evidence | Train? |
|---|---|---|---|---|
| B0 | none | — | — | — |
| B1 | rules | 4-way (+binary proj.) | full | no |
| B2 / B3 | prompted Qwen3-8B | 2 / 4-way | full | no |
| B4 | QLoRA | 2-way, threshold swept | full | yes |
| B5 | QLoRA | 4-way | full | yes |
| B5 − prov / − auth / − RAG | QLoRA | 4-way | field masked | yes (retrained) |
| B5 − ASK / − ESC | QLoRA | 3-way | full | yes |
| B5 − intermediate | QLoRA | 4-way | full, no intermediate targets | yes |
| B5 inferred-prov | B5 adapter | 4-way | inferred provenance | no (test-time swap) |

→ 8 QLoRA runs in total.

---

## 8. Evaluation (`eval/`)

`metrics.py` consumes `predictions/<condition>.jsonl` (one `ResolutionTrace` per case) and the gold set:
final-resolution success, unauthorized-action rate, unnecessary-deferral rate (+ raw deferral vs gold
prevalence), mean interactions, clarification success, escalation precision/recall, macro-F1 for
`missing_evidence` / `required_authority`, Recall@3/5, provenance attribution accuracy, authority-spoofing
success, clean vs noisy splits; on the executable subset also AgentDojo utility, attack success rate, tool
selection accuracy and argument validity.

`stats.py`: paired bootstrap 95% CIs (10k resamples, seeded), exact McNemar for paired per-case success,
Holm–Bonferroni over the ablation family, Krippendorff's α (nominal) + pairwise Cohen's κ for annotation.
Reports always print raw counts with percentages (`3/61 (4.9%)`). `pareto.py` draws the
unauthorized-action vs final-resolution-success frontier with the success region (≤5% / ≤10%).

---

## 9. Kaggle execution plan

### 9.1 Environment

| Item | Choice |
|---|---|
| Accelerator | **GPU T4 ×2** (16 GB each). One 8B nf4 model (~6 GB) per GPU → two independent jobs in parallel per notebook (`CUDA_VISIBLE_DEVICES=0` / `1`). |
| Code | Notebook cell clones this repo (internet on) and `pip install -e .[train]`; or the repo is attached as a Kaggle Dataset for offline runs. |
| Data | Comes with the repo (`data/processed/agentdojo`, 27 MB). |
| Model | `Qwen/Qwen3-8B` from Hugging Face (or the Kaggle Models copy attached under `/kaggle/input`), quantised on load; `Qwen/Qwen3-8B-AWQ` for vLLM. HF cache under `/kaggle/working/hf` or `/kaggle/tmp`. |
| Secrets | `HF_TOKEN` via Kaggle Secrets (only if needed). No external LLM APIs. |
| Outputs | `/kaggle/working/outputs/<stage>/…`; "Save Version" turns them into a Kaggle Dataset (`sagate-outputs-<stage>`) that the next notebook attaches as input. |
| Limits | 12 h per session, ~30 GPU-h/week per account → work is split across the four team accounts; all jobs resumable. |

`config.py` detects Kaggle (`KAGGLE_KERNEL_RUN_TYPE`) and switches paths via `configs/kaggle.yaml`.

### 9.2 Notebooks

| NB | Purpose | Accelerator | Inputs → outputs | Est. GPU-h |
|---|---|---|---|---|
| NB00 `setup_smoke` | install, load Qwen3-8B nf4, one gate call, one AgentDojo task, unit tests | T4 | → env check | 0.5 |
| NB01 `b0_traces` | Qwen3-8B agent over all strict train/test scenarios (benign + injection, `important_instructions` attack) → traces + proposals in dataset schema; ground-truth replay fallback | T4×2 (vLLM, parallel scenarios) | dataset → `b0_traces/` | 3–5 |
| NB02 `baselines_prompted` | B1 (CPU), B2, B3 on test + dev, with resolution loop; inferred-provenance attribution | T4×2 (GPU0 = B2, GPU1 = B3) | cases → `predictions/` | 2–4 |
| NB03 `train_qlora` | one condition per GPU per run; 8 conditions → 4 sessions | T4×2 | `sft/` → `adapters/<cond>/` | 6–12 |
| NB04 `eval_learned` | B4 (incl. dev threshold sweep), B5, ablations, inferred-prov swap; clean vs noisy | T4×2 | adapters + cases → `predictions/` | 3–5 |
| NB05 `e2e_agentdojo` | B0 vs B5 (B3 if time) end-to-end on test-source executable scenarios | T4×2 (agent on GPU0 via vLLM, gate on GPU1 via HF) | adapters → `e2e/` | 4–7 |
| NB06 `stats_report` | metrics, CIs, McNemar, Holm, Pareto, qualitative example picker | CPU | `predictions/`, `e2e/` → `report/` | 0 |

CPU-only steps (case building, variant generation, SFT build, B1, stats) also run locally; their outputs are
committed or uploaded as datasets so GPU sessions are spent only on model work. Total ≈ 19–34 GPU-h, inside
the proposal's 22–39 h estimate.

### 9.3 Resumability
Every GPU loop writes `{"key": sha1(condition, case_id, round, prompt), …}` lines with `flush()` after each
item and skips keys already present on restart. Training saves PEFT checkpoints every 100 steps and resumes
from the latest. Each output folder has a `manifest.json` (git commit, config hash, model revision, seeds,
library versions).

---

## 10. Leakage and correctness guards

- `splits.assert_pool()` on every generated training case (`strict_split == "train"`, dev allowed) and every
  test case (`== "test"`); CI test fails if any ID crosses.
- B4 threshold uses dev only; the code path for threshold selection cannot load test predictions.
- Unit tests: mask removes fields from both rendered prompt and SFT target; decoder always emits valid JSON;
  resolution loop defaults to BLOCK after 2 rounds; a user reply never flips `user_may_authorize`; metrics on
  hand-computed toy cases.

---

## 11. Risks specific to the Kaggle build

| Risk | Mitigation |
|---|---|
| vLLM no longer supports T4 (sm 7.5) in the pinned version / AWQ kernels fail | Verify in NB00 week 1; fallback = HF backend with batched parallel scenarios (slower, still within budget for ~420 runs). |
| fp16 overflow during QLoRA on T4 | Keep LoRA in fp32, gradient clipping 0.3; fall back to P100 or smaller lr. |
| Qwen3 tool-calling format mismatch with AgentDojo | Use Hermes tool parser (vLLM) or a custom prompt-based tool-call parser element; fallback = ground-truth replay as proposals (proposal §13). |
| Session timeouts | All jobs resumable (Section 9.3); jobs sized to ≤ 9 h. |
| Gate prompt + untrusted content exceeds context | Truncate each untrusted block to 512 tokens, keep only the most recent 3 tool outputs, max input 3,072 tokens. |

---

## 12. Open decisions for the team

1. **Output field order** — intermediate fields before `decision` (current plan, acts as structured
   reasoning) vs decision first.
2. **Read-only tools** — bypass the gate (current plan) or gate everything.
3. **Collapse rule for `b5_no_ask` / `b5_no_esc`** — map removed class to `gold_final_action` (current plan)
   or to the other deferral class.
4. **Inferred provenance in training** — train with oracle and swap at test time (current plan) vs. retrain.
5. **Attack type for Qwen B0 traces** — `important_instructions` only (current plan) or add `direct` /
   `ignore_previous`.
6. **Authority YAML and handbooks** — owner(s) and freeze date (needed before variant generation).
