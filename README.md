# Security-Aware Tool-Using LLM Agent

CL3410 (Language Models and Agents, IIIT Hyderabad, Monsoon 2026) group project
*Provenance- and authority-aware resolution of tool actions at runtime*.

A runtime security gate sits between a Qwen3-8B tool agent and its tools. For every state-changing call it
assembles provenance, authority, sensitivity and policy (RAG) evidence and decides ALLOW / BLOCK / ASK_USER /
ESCALATE; ASK_USER and ESCALATE collect one more piece of evidence and re-run the same gate (at most two rounds,
then BLOCK).

## Code (`secgate`)

| Path | Contents |
|---|---|
| `src/secgate/data/` | dataset loaders, frozen split + leakage guard, case builder, ground-truth matching |
| `src/secgate/evidence/` | tool registry, provenance (oracle / inferred), authority registry, sensitivity labels, BM25 policy retrieval, evidence masks, context builder |
| `src/secgate/gate/` | schema, prompt renderer, B1 rules, enum-scoring constrained decoder, LLM gate (B2–B5) |
| `src/secgate/resolution/` | resolution loop, fixed / scenario user responders, mock approver |
| `src/secgate/models/` | Hugging Face backend (nf4 + PEFT, KV-cache reuse), Qwen3 chat and tool-call parsing |
| `src/secgate/agent/` | AgentDojo pipeline with a local Qwen3 agent, B0 trace runner, proposal extraction |
| `src/secgate/eval/` | gate runner, metrics, report |
| `configs/` | base settings, Kaggle overrides, one YAML per experimental condition |
| `resources/` | synthetic authority state, sensitivity labels, the two clause-tagged policy handbooks |
| `docs/ANNOTATION_GUIDE.md` | label definitions and decision procedure for the human test set |
| `notebooks/kaggle_pipeline.ipynb` | the single Kaggle notebook that runs every stage |

Baselines implemented so far: **B0** (Qwen3-8B agent, no gate), **B1** (deterministic rules), **B2** (prompted
binary gate), **B3** (prompted four-way gate).

### Run locally (CPU parts and small-model smoke tests)

```bash
pip install -e ".[dev]"                       # + ".[gpu,agentdojo]" for the model and agent parts
pytest
python -m secgate.data.build_cases --pool test
python -m secgate.eval.run_gate --condition b1_rules --cases outputs/cases/test_candidates.jsonl --pool test
python -m secgate.eval.report --cases outputs/cases/test_candidates.jsonl --pred outputs/predictions/test/*.jsonl
python -m secgate.smoke --model-id Qwen/Qwen3-0.6B    # needs torch + transformers (+ agentdojo for the agent task)
```

### Run on Kaggle

Full step-by-step guide: [docs/KAGGLE.md](docs/KAGGLE.md). In short:

1. `python scripts/stage_kaggle_code.py --owner <kaggle-user>`, then
   `kaggle datasets create -p build/kaggle-code --dir-mode zip` (later: `kaggle datasets version ...`).
2. Open `notebooks/kaggle_pipeline.ipynb` on Kaggle (GPU T4 x2, internet on), attach the `secgate-code`
   dataset, choose `STAGES`, and run with `SMOKE = True` first, then `SMOKE = False`.

## Dataset

The base data is AgentDojo's **workspace** and **banking** suites, exported to flat JSON/JSONL, plus logged
AgentDojo agent runs used as a pool of tool-call proposals. The human-annotated test set and the generated
training variants are added under `annotations/` later.

## Where the data comes from

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

## Contents and counts

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

## Train / dev / test split

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

## Schema

### `user_tasks.jsonl`
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

### `injection_tasks.jsonl`
Same as above with `goal` (attacker instruction) instead of `prompt`, and no `injection_vectors`.

### `injection_vectors.jsonl`
`suite`, `vector_id`, `description`, `default` (benign text in the slot), `reached_by_user_tasks`.

### `tools.jsonl`
`suite`, `name`, `module`, `description`, `parameters` (list of `name`, `type`, `description`, `required`, `default`).

### `scenarios.jsonl`
`scenario_id` (`suite|user_task|injection_task-or-benign`), `suite`, `user_task_id`, `injection_task_id`,
`type` (`benign` | `injection`), `injection_vectors`, `user_task_split`, `injection_task_split`, `strict_split`.

### `traces.jsonl.gz`
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

### `tool_call_proposals.jsonl.gz` — one row per proposed tool call
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

## Caveats

- Run logs have no benchmark-version field; some were produced against older task versions (v1.0–v1.1).
- Provenance is substring matching; numbers, dates and short values are often `unknown`.
- 468 injection-only runs (no user task) are not exported. Slack and travel suites are out of scope.
- See [`data/processed/agentdojo/README.md`](data/processed/agentdojo/README.md) for additional notes.
