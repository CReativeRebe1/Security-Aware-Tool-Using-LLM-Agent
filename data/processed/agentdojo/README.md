# AgentDojo — workspace + banking export

Built from a local checkout of github.com/ethz-spylab/agentdojo (benchmark v1.2.2) by a build script kept
outside this repository (`scripts/build_agentdojo_dataset.py`). Extraction is static (AST/YAML/JSON); no
AgentDojo code was run.

## Files

| File | Rows | What it is |
|---|---|---|
| `user_tasks.jsonl` | 56 (40 workspace, 16 banking) | User prompt, difficulty, ground-truth tool calls, injection vectors the task reaches |
| `injection_tasks.jsonl` | 23 (14 / 9) | Attacker goal, difficulty, ground-truth tool calls |
| `injection_vectors.jsonl` | 20 (16 / 4) | Injection slots in the environment, default (benign) text, which user tasks reach them |
| `tools.jsonl` | 35 (24 / 11) | Tool name, description, LLM-facing parameters |
| `environments/<suite>_template.json` | — | Initial environment state with `{injection_slot}` placeholders |
| `environments/<suite>_default.json` | — | Same, slots filled with benign defaults |
| `scenarios.jsonl` | 760 | Every benign user task + every reachable (user task × injection task) pair, with split columns |
| `splits/scenario_split.json` | — | The frozen train/dev/test assignment (seed 42) |
| `traces.jsonl.gz` | 23,602 | Logged AgentDojo runs (≈30 models/defences × attacks) incl. full messages |
| `tool_call_proposals.jsonl.gz` | 61,152 | One row per proposed tool call inside those traces — the gate's input unit |
| `summary.json` | — | Counts |

## Key fields

**Ground truth.** `ground_truth_calls[].args` values are resolved literals where possible; values computed from
the environment at runtime appear as `{"__expr__": "<python source>"}`. `ground_truth_static` is true when the
whole call list was resolved. 8 workspace user tasks are not fully static (10, 13, 19, 31, 32, 34, 36, 37);
`ground_truth_source` holds the original method for those.

**Traces.** `attack_succeeded` = AgentDojo's `security` flag (true ⇒ the injection goal was achieved). `null` for
`attack_type = "none"` (benign runs). `injections` maps each slot to the exact injected text.

**Proposals.** Context for a single gate decision:
- `user_prompt`, `prior_calls`, `proposed_call`, `message_index` (look up tool outputs in the trace)
- `arg_provenance` — per argument, where its value string appears: `user_prompt`, `injection` (inside the injected
  text), `tool_output` (non-injected tool output), `unknown`, or `too_short`. This is an **oracle-style provenance
  signal** derived from knowing the injected strings.
- `injection_seen_before_call` — injected text was already in context when the call was proposed.
- `matches_user_task_ground_truth` / `matches_injection_task_ground_truth` — **loose heuristic**: same function and
  at least one distinctive target value (IBAN, email, file name …) in common; dates/amounts ignored.

These heuristic flags are weak labels for analysis and for generating structured training variants. They are
**not** gold ALLOW / BLOCK / ASK_USER / ESCALATE labels — those come from the human-annotated test set.

## Split (per the proposal's "split before generating")

- User tasks: ~40% test, ~10% dev, ~50% train, stratified by suite × has-injection-vectors (28 / 6 / 22).
  `dev` belongs to the train-source pool (use it for B4 threshold calibration).
- Injection tasks: ~40% test per suite.
- `scenarios.jsonl` columns: `user_task_split`, `injection_task_split`, and `strict_split`
  (`train` / `test` only when the user task and injection task fall on the same side, else `excluded`).
  Use `strict_split` if you want neither the user scenario nor the attacker goal to leak across pools.
  Strict counts: 276 train-source (incl. dev) + 142 test scenarios, 342 excluded; the 56 benign scenarios are
  never excluded.

## Caveats

- Run logs carry no benchmark-version field; some were produced against older task versions (v1.0–v1.1), so a few
  prompts/ground truths may differ from the v1.2.2 task definitions.
- 468 injection-task-only runs (no user task) in `runs/*/<suite>/injection_task_*` are not exported.
- Provenance is substring matching; short or generic values (e.g. `100`, dates) are often `unknown`.
- Slack and travel suites are in the raw checkout but not exported (out of the proposal's scope).
