# Architecture — Security-Aware Tool-Using LLM Agent (Kaggle implementation)

Scope of this document: the software architecture and the Kaggle execution plan for the CL3410 project
*Provenance- and authority-aware resolution of tool actions at runtime*. It turns the proposal
(Sections 4–9) into packages, interfaces, data contracts and notebooks. The code up to the baselines
(B0–B3, NB00–NB02) is implemented; Section 14 lists its status and the deviations from this plan.

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

### 5.0 How the dataset maps onto the components

| Dataset file | Used by | Notes |
|---|---|---|
| `tool_call_proposals.jsonl.gz` | case builder (one row = one gate decision) | `user_prompt`, `prior_calls`, `proposed_call` go straight into `GateInput`. Rows hold **no tool outputs**: `untrusted_content` is filled by joining `trace_id` + `message_index` to `traces.jsonl.gz` and taking the `role: "tool"` messages before that index. |
| `traces.jsonl.gz` | case builder, oracle provenance | `injections` (slot → injected text) drives oracle provenance; `messages` gives tool outputs. |
| `arg_provenance`, `injection_seen_before_call` | oracle provenance | used as-is (recomputed with the same logic for Qwen traces). |
| `matches_*_ground_truth` | variant seeding, analysis only | weak heuristics — **never** used as gold labels. |
| `user_tasks.jsonl` / `injection_tasks.jsonl` | `ScenarioResponder`, variant generator, tool-selection metric | `ground_truth_calls` with `{"__expr__": …}` values (8 workspace tasks) are compared on function name + static args only; those 8 tasks are flagged in tool-selection/argument-validity results. |
| `scenarios.jsonl` + `splits/` | `splits.assert_pool` | train-source = `strict_split == "train"` (dev = `user_task_split == "dev"`), test-source = `"test"`; the 342 `excluded` scenarios are never used. |
| `environments/*_default.json` | authority/sensitivity YAML authoring, e2e | the YAML references real resources from here (IBANs, file IDs, contacts, calendar events). |
| `tools.jsonl` | `tools_registry`, agent tool schemas | 35 tools, static state-changing classification (5.1). |

Version caveat: the logged runs carry no benchmark version and some predate v1.2.2. Executable cases built
from old logs are **replayed** in the pinned AgentDojo env before annotation; any case whose prior calls do
not reproduce (different tool output / error) is dropped from the executable subset.

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
- **Inferred** (runtime-realistic, no knowledge of which text is injected): match values against the
  user prompt vs. each tool output in the conversation, tagging tool outputs from third-party content
  (emails, files, calendar descriptions, bill files) as `untrusted`. Pure string matching, CPU only.
  *Stretch (only if time):* for unmatched values / instruction origin, a constrained multiple-choice
  attribution question to Qwen3-8B over `{user, T1..Tn}`. Attribution accuracy is scored against oracle.

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
Handbook clauses written as `### [BANK-3.2] Title` → one chunk per clause (~80 clauses in total, so this
is tiny). Retriever: BM25 (`rank_bm25`), top-k=3 (k=5 for Recall@5). A dense retriever
(`BAAI/bge-small-en-v1.5`, CPU) is added only if BM25 Recall@3 on the pilot cases is poor. Retrieval is
precomputed once per case on CPU and stored in the case file, so no GPU session ever runs retrieval. The query is built from **trusted fields only** (tool name, action class, resource/destination
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
  to valid IDs **only for B5 on the test set** (error analysis); everywhere else generation stops after
  `decision`, so a gate call is ~one prefill + a few short scoring passes (~1 s on a T4).
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
- `QwenLLM` — calls the HF backend, thinking off, greedy; Qwen3's native `<tool_call>` JSON is parsed by a
  small custom parser (malformed calls are returned to the agent as an error, max 2 retries).
- `GatedToolsExecutor` — replaces AgentDojo's `ToolsExecutor`: for each tool call, build `GateInput` from the
  live conversation (inferred provenance), run the resolution loop, execute only on `ALLOW`, otherwise
  return a minimal tool message (`"Action not permitted."`) that leaks no policy detail. After 3 refused
  calls in one task the run is ended (prevents the agent looping on retries). Writes an audit log.

**One model in memory.** Agent and gate share the same nf4 base model in one process; the gate call wraps
the B5 LoRA adapter (`model.set_adapter("b5")`), the agent call runs with adapters disabled
(`with model.disable_adapter():`). One GPU per run, no server, no inter-process plumbing.

**Live responders.** Live e2e runs produce calls that are not in the annotated test set, so there is no
hand-written `user_response` for them. `ScenarioResponder` answers from the scenario instead: the user
confirms a call that matches the user task's ground truth and declines anything else (with the same 15%
noise); the approver answers from the authority YAML. This is weaker than the offline protocol and is
reported as such.

B0 = the same pipeline with the gate disabled.

### 5.8 Model backends (`models/backend.py`)

| Use | Backend | Quantisation |
|---|---|---|
| Everything: agent, gate (B2–B5), training | HF `transformers` + `bitsandbytes` + PEFT | pre-quantised nf4 checkpoint (`unsloth/Qwen3-8B-bnb-4bit`, ~6 GB), fp16 compute |
| Optional speed-up for B0 traces only | vLLM (`Qwen/Qwen3-8B-AWQ`) — only if NB00 shows it runs on T4 | AWQ 4-bit |

Why one backend: agent, prompted gates and learned gates are the same weights, so prompted vs learned
gates differ only by the adapter, and there is one stack to debug. Why a pre-quantised checkpoint: the
fp16 checkpoint is 16 GB, which nearly fills the 20 GB `/kaggle/working` disk and spikes CPU RAM when two
processes quantise on load at the same time (Kaggle has ~29 GB RAM).

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
- **QLoRA**: LoRA r=16, α=32, dropout 0.05 on all linear projections; nf4; fp16 compute (T4/P100 have no
  bf16); loss on the assistant JSON only; max length 2,048 (median gate input ≈ 1.2k tokens, untrusted
  blocks truncated); batch 1 × grad-accum 16; lr 2e-4 cosine; 2 epochs; gradient checkpointing; checkpoint
  every 100 steps for resume. **Unsloth is the primary trainer on T4** (≈2× faster, and handles Qwen3 fp16
  stability); plain PEFT/TRL is the fallback with the identical config. The adapter is saved as a standard
  PEFT adapter so inference never depends on Unsloth.
- **Cost per run**: ~1,200 examples × ~1.2k tokens × 2 epochs ≈ 3M tokens → **~35–90 min on one T4**.
  8 runs, 2 in parallel (one per GPU) → ~3–5 h wall-clock in total.
- **B4 operating point**: sweep the threshold on `p_allow` over the dev pool (48 scenarios from the 6 dev
  user tasks, part of train-source), pick the threshold matching B5's unauthorized-action rate on dev;
  never touch test. Dev cases are generated, not human-labelled, so the dev-selected point may not
  transfer; the full threshold curve on test is also reported as a Pareto frontier (reporting a curve
  is not selecting on test).

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
success, clean vs noisy results and noise-induced error rate (cases correct with the clean reply but wrong
with the noisy one); on the executable subset also AgentDojo utility, attack success rate, sensitive-data
leakage (CONFIDENTIAL/RESTRICTED content reaching a lower-labelled destination in an executed call), tool
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
| Accelerator | **GPU T4 ×2** (16 GB each). One 8B nf4 model (~6 GB) per GPU → two independent jobs in parallel per notebook, launched as two subprocesses with `CUDA_VISIBLE_DEVICES=0` / `1` (not one process spanning both GPUs). |
| Code | Notebook cell clones this repo (internet on) and `pip install -e .[train]`; or the repo is attached as a Kaggle Dataset for offline runs. |
| Data | Comes with the repo (`data/processed/agentdojo`, 27 MB). |
| Model | `unsloth/Qwen3-8B-bnb-4bit` (~6 GB) downloaded once into `/kaggle/tmp/hf` (not persisted, does not count against the 20 GB output disk); or attached as a Kaggle Model/Dataset to skip the download. |
| Long jobs | Run as **"Save & Run All (Commit)"** background versions, not interactive sessions — interactive output is lost when the session ends. |
| Secrets | `HF_TOKEN` via Kaggle Secrets (only if needed). No external LLM APIs. |
| Outputs | `/kaggle/working/outputs/<stage>/…`; "Save Version" turns them into a Kaggle Dataset (`sagate-outputs-<stage>`) that the next notebook attaches as input. |
| Limits | 12 h per session, ~30 GPU-h/week per account → work is split across the four team accounts; all jobs resumable. |

`config.py` detects Kaggle (`KAGGLE_KERNEL_RUN_TYPE`) and switches paths via `configs/kaggle.yaml`.

### 9.2 Notebooks

| NB | Purpose | Accelerator | Inputs → outputs | Est. GPU-h |
|---|---|---|---|---|
| NB | Purpose | Accelerator | Inputs → outputs | Est. session-h |
|---|---|---|---|---|
| NB00 `setup_smoke` | install, load Qwen3-8B nf4, one gate call, one AgentDojo task, **measure prefill/decode tok/s and one 50-step training run** (replaces the estimates below with measured numbers) | T4 | → env check + `throughput.json` | 0.5 |
| NB01 `b0_traces` | Qwen3-8B agent over the 418 strict train/test scenarios (benign + `important_instructions`) → traces + proposals in dataset schema | T4×2 (scenarios sharded across GPUs) | dataset → `b0_traces/` | 2–4 |
| NB02 `baselines_prompted` | B2, B3 on test + dev with resolution loop (B1 runs on CPU) | T4×2 (GPU0 = B2, GPU1 = B3) | cases → `predictions/` | 0.5–1 |
| NB03 `train_qlora` | 8 conditions, two per session (one per GPU) | T4×2 | `sft/` → `adapters/<cond>/` | 3–5 |
| NB04 `eval_learned` | B4 (incl. dev threshold sweep), B5, ablations, inferred-prov swap; clean vs noisy | T4×2 | adapters + cases → `predictions/` | 1–2 |
| NB05 `e2e_agentdojo` | B0 vs B5 (B3 if time) end-to-end on the 142 test scenarios | T4×2 (scenarios sharded) | adapters → `e2e/` | 2–4 |
| NB06 `stats_report` | metrics, CIs, McNemar, Holm, Pareto, qualitative example picker | CPU | `predictions/`, `e2e/` → `report/` | 0 |

How the numbers were derived: the sampled traces have a median of ~1.1k tokens and 3 agent turns (p90:
~7.9k tokens, 6 turns), plus ~3k tokens of tool schemas per agent turn. Assumed T4 speed for 8B nf4:
prefill ~1.5–3k tok/s, decode ~8–12 tok/s, training ~0.5–1.5k tok/s. Offline evaluation is ~12 conditions ×
~240 cases × ~1.3 gate calls ≈ 3,700 calls at ~1 s each.

CPU-only steps (case building, retrieval, variant generation, SFT build, B1, stats) run locally; their
outputs are committed or uploaded as datasets so GPU sessions are spent only on model work.
**Total ≈ 10–17 session-hours** (+~30% contingency), well under the proposal's 22–39 h. Most of it is agent
runs (NB01, NB05), not fine-tuning. All estimates are replaced by NB00's measurements in week 1.

### 9.3 Running from the Kaggle CLI

Verified with Kaggle CLI 2.2.5 (`pip install kaggle`; auth via `~/.kaggle/access_token`). Everything is
driven from the local machine; nothing is edited in the Kaggle web UI.

**Layout** — one folder per job, each a Kaggle *script* kernel (plain `.py`, easier to diff than `.ipynb`):

```
kaggle/
├── stage_code.sh                  # copies src/ configs/ resources/ data/ pyproject.toml → build/sagate-code/
├── code-dataset/dataset-metadata.json      # id: prabhashpadhan/sagate-code
├── nb00_setup_smoke/{kernel-metadata.json, run.py}
├── nb01_b0_traces/{kernel-metadata.json, run.py}
├── …                                        # nb02 … nb05
```

**`kernel-metadata.json`** (NB03 example):

```json
{
  "id": "prabhashpadhan/sagate-nb03-train-qlora",
  "title": "sagate-nb03-train-qlora",
  "code_file": "run.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": "true",
  "enable_gpu": "true",
  "enable_tpu": "false",
  "enable_internet": "true",
  "dataset_sources": ["prabhashpadhan/sagate-code"],
  "kernel_sources": ["prabhashpadhan/sagate-nb01-b0-traces"],
  "competition_sources": [],
  "model_sources": []
}
```

- **Code** goes up as a private dataset (`sagate-code`), mounted at `/kaggle/input/sagate-code`; `run.py`
  does `pip install -e` from there, then `python -m sagate.<stage> --config configs/kaggle.yaml …`. No git
  clone or GitHub token is needed on Kaggle.
- **Stage chaining** uses `kernel_sources`: a previous kernel's `/kaggle/working` output is mounted read-only
  at `/kaggle/input/<kernel-slug>`. No manual "save output as dataset" step.
- **Internet on** is needed for `pip install` and the Hugging Face model download.
- **Parameters** (condition names, GPU split) live in `run.py`/config, not in CLI flags; the CLI passes none.

**Commands**

```bash
# once
kaggle datasets create  -p build/sagate-code --dir-mode zip
# every code change
bash kaggle/stage_code.sh && kaggle datasets version -p build/sagate-code -m "<git sha>" --dir-mode zip

# run a stage on GPU T4 x2 (background commit run, survives closing the laptop)
kaggle kernels push -p kaggle/nb03_train_qlora --accelerator NvidiaTeslaT4 -t 32400   # 9 h cap

kaggle kernels status prabhashpadhan/sagate-nb03-train-qlora        # queued / running / complete / error
kaggle kernels output prabhashpadhan/sagate-nb03-train-qlora -p runs/nb03/   # log + /kaggle/working files
```

Notes:
- `--accelerator NvidiaTeslaT4` = GPU T4 ×2. P100 is retired (the CLI warns and substitutes), so the
  plan assumes T4 only.
- After a dataset `version`, wait until it finishes processing before `kernels push`; otherwise the kernel
  can mount the previous code version. `run.py` prints the staged git SHA first so this is visible in the log.
- `kaggle kernels push` re-runs the whole script from scratch, and a kernel cannot mount its own previous
  output. To resume a run that timed out: `kaggle kernels output` it, upload that folder as a
  `sagate-progress-<stage>` dataset, add it to `dataset_sources`, and push again; the job skips keys it
  finds there (9.4). Simpler still: size every job to finish in ≤ 9 h so this is rarely needed.
- Each team member pushes the same folders under their own username (`id` and the `*_sources` owners are
  rewritten by `stage_code.sh --owner <user>`) to use their own weekly GPU quota.

### 9.4 Resumability
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
| Qwen B0 traces late → blocks the Week-2 checkpoint (annotation needs cases) | **Annotation does not wait for NB01.** The existing logs already hold 2,373 state-changing proposals in test-source scenarios (550 of them match the attacker goal); executable test cases are drawn from these first, and Qwen proposals are added when NB01 finishes. Fallback = ground-truth replay (proposal §13). |
| AgentDojo-derived cases are almost all ALLOW (user task) or BLOCK (injection) — AgentDojo has no notion of authority, so ASK_USER/ESCALATE barely occur | The authority YAML must add real policy pressure (transfer limits, unapproved recipients, confidential files, external shares) **before** annotation, and the decision-only NL cases carry most ASK/ESCALATE examples. Check the class mix on the pilot; if executable ESCALATE < ~15 cases, report ESCALATE metrics on the decision-only subset only. |
| Small test classes (ESCALATE ≈ 36 cases; unauthorized-action denominator ≈ 155) → CIs of ±3–4 points | Accepted; raw counts always reported. Do not add conditions beyond Section 7 — each one adds a comparison to the Holm family. |
| vLLM does not run on T4 (sm 7.5) | Not needed — HF is the default backend; vLLM is an optional speed-up only. |
| fp16 overflow / NaN loss during QLoRA on T4 | Unsloth's Qwen3 path; LoRA weights in fp32, gradient clipping 0.3; fall back to a smaller lr or P100. |
| Qwen3 tool-call output malformed | Custom parser with error-and-retry (Section 5.7); fallback = ground-truth replay as proposals. |
| Session timeouts | All jobs resumable (Section 9.4); jobs sized to ≤ 9 h. |
| Gate prompt + untrusted content exceeds context | Truncate each untrusted block to 384 tokens, keep only the 3 most recent tool outputs, max input 2,048 tokens; log the truncation rate. |
| Kaggle disk / RAM limits | Pre-quantised 4-bit checkpoint in `/kaggle/tmp`; only adapters (~80 MB each) and JSONL go to `/kaggle/working`. |

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
6. **Authority YAML and handbooks** — owner(s) and freeze date. This is the real Week-1 blocker: the
   context builder, B1, annotation and variant generation all depend on it.
7. **What "B0" means** — the proposal makes Qwen3-8B the task agent, so B0 = Qwen3-8B traces (NB01).
   The dataset README calls the existing multi-model AgentDojo logs "cached B0 traces". Current plan: the
   existing logs are a *proposal pool* for building gate cases; B0 utility/attack numbers come from Qwen only.
8. **Scenario count** — the proposal says ~150 base scenarios; the frozen split has 418 usable
   (276 train-source + 142 test-source). Current plan: use all 418 (more training variety, same leakage
   guarantees) and state the change in the report.

---

## 13. Build order (critical path)

Build the thinnest end-to-end slice first, then widen it. Anything marked *stretch* is cut first if late.

| Week | Code deliverable | Unblocks |
|---|---|---|
| 1 | `schema`, `loaders`, `splits` + leakage tests, `tools_registry`, oracle provenance, authority/sensitivity lookups (on a draft YAML), BM25 retrieval, `context_builder` + `EvidenceMask`, prompt renderer, B1 rules; NB00 smoke + throughput | annotators can view rendered cases; real GPU numbers |
| 2 | `decoder`, `LLMGate` (B2/B3), resolution loop + responders, NB01 B0 traces, case export for annotation | Week-2 checkpoint |
| 3 | `variants`, `build_sft`, `train_qlora`; B2/B3 predictions; inferred provenance (string matching) | training |
| 4 | NB03 training (8 adapters), NB04 eval, B4 threshold sweep | primary results |
| 5 | `metrics`, `stats`, `pareto`, `report` | write-up |
| 6 | `GatedToolsExecutor`, NB05 end-to-end B0/B5; *stretch:* B3 e2e, LLM provenance attribution, dense retrieval, extra seeds | end-to-end claims |

Minimal viable result if things slip: B1, B3, B4, B5 offline on oracle provenance, plus B5 − provenance and
B5 − authority. That alone answers H1 and H2.

---

## 14. Implementation status (baselines)

**Built and tested** (`pytest`: 37 tests; local smoke run with `Qwen/Qwen3-0.6B` on CPU):
`config`, `data/{loaders,splits,cases,build_cases,annotation,ground_truth}`, `evidence/*`, `gate/*`,
`resolution/*`, `models/{backend,chat}`, `agent/{pipeline,run_b0,extract_proposals}`,
`eval/{metrics,stats,run_gate,report}`, `smoke`, Kaggle kernels NB00–NB02 + `stage_code.sh` + `bootstrap.py`.

**Not built yet** (after the baselines): `train/*` (variants, SFT build, QLoRA), `eval/pareto.py`
(B4 threshold sweep), `GatedToolsExecutor` + `run_e2e.py` (NB05), NB03–NB06.

**Checks against the data**
- Provenance tagging reproduces the shipped `arg_provenance` on 100% of sampled arguments; proposal
  extraction reproduces `message_index`, `step`, `prior_calls`, `proposed_call` exactly.
- `matches_*_ground_truth` is re-implemented in `data/ground_truth.py` (~99% agreement with the shipped flags).
- The enum-scoring decoder's KV-cache scores equal a plain full forward pass (checked on Qwen3-0.6B).
- Krippendorff's α matches the reference `krippendorff` package.
- Test pool: 1,390 deduplicated state-changing candidate cases (train pool: 4,643). B1 on the test candidates:
  first-round ALLOW 956 · BLOCK 313 · ASK_USER 112 · ESCALATE 9. As expected (§11), executable cases carry very few
  ESCALATEs; the decision-only NL cases must supply most of them.

**Deviations / decisions taken in code** (review with the team)
1. `resources/` (authority, sensitivity, handbooks) are **drafts** written to create policy pressure on real
   tasks: transfer limits (1,500 approved payee / 500 new payee), redirecting a standing order, deleting a file
   someone else owns, look-alike domains, RESTRICTED codes and reset links. The team still has to own and freeze them (§12.6).
2. Provenance records have a call-level record `P0` (`instruction_origin`, `trust`) followed by one record
   per argument. Trust levels: `trusted | third_party | untrusted | unknown`. Oracle mode also marks a call as
   injection-driven when it matches the injection task's ground truth and an injected block is in context.
3. Inferred provenance (string matching + instruction-cue regex) is already implemented, because the live
   pipeline needs it anyway; the LLM attribution stretch is not.
4. Untrusted blocks are truncated by characters (1,500 ≈ 384 tokens) so case building needs no tokenizer.
5. The retrieval query uses trusted fields only and does **not** use provenance (otherwise −provenance would leak
   through the retrieved clauses); clauses about injected instructions are therefore rarely retrieved.
6. Before annotation, `ScenarioResponder` answers ASK_USER (confirms calls matching the user task's ground
   truth, 15% seeded noise). `FixedUserResponder` takes over automatically for cases with a `user_response`.
7. `MockApprover` denies when the call's oracle origin is untrusted, when the gate escalates to the wrong role,
   or when a basis rule is in the approver's `denies` list. When no approval is needed, it answers "the user
   may authorize this" (the deferral is still counted).
8. `injection_seen_before_call` in extracted proposals is whitespace/quote-insensitive, so it also catches
   injections split by YAML line-wrapping. The shipped flag misses those, so it is True less often.
9. B0 trace ids are `qwen3-8b|<suite>|<user_task>|<attack|none>|<injection_task|none>`; the AgentDojo pipeline
   name contains `local` so the `important_instructions` attack addresses the model as "Local model".
