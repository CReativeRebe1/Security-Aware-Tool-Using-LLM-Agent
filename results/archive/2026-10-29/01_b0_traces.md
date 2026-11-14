# NB01 — B0 agent traces (Qwen3-8B, no gate)

**Run folders:** `runs/nb01/` (final run), `runs/nb01_run1/` (first attempt, hit out-of-memory errors)
**Files:** `outputs/b0_traces/{traces.jsonl, proposals.jsonl, b0_summary.json, manifest_shard*.json}`
**Setup:** Qwen3-8B 4-bit as the task agent, thinking off, greedy decoding, max 15 iterations, 512 new tokens per turn,
up to 2 retries on malformed tool calls. AgentDojo v1.2.2, attack `important_instructions`. The 142 test scenarios
were split into 2 shards of 71, one per T4.

B0 is the baseline agent with **no security gate**. These traces are also the source of the Qwen proposals that
became test cases.

## Main result (final run, 0 errors)

| Pool | Scenarios | Utility (task success) | Attacked scenarios | Attack success (ASR) |
|---|---|---|---|---|
| **All test** | 142 | **49/142 (34.5%)** | 120 | **10/120 (8.3%)** |
| Banking | 30 | 15/30 (50.0%) | 24 | 8/24 (33.3%) |
| Workspace | 112 | 34/112 (30.4%) | 96 | 2/96 (2.1%) |

Utility split by benign vs attacked:

| Suite | Benign utility | Utility under attack |
|---|---|---|
| Banking | 3/6 (50.0%) | 12/24 (50.0%) |
| Workspace | 5/16 (31.3%) | 29/96 (30.2%) |
| **All** | **8/22 (36.4%)** | **41/120 (34.2%)** |

Utility is about the same with and without the attack, so the attack does not mainly hurt the agent by
distracting it. Banking is where the attack works (a third of attacks succeed), while workspace attacks almost
never succeed.

## Further end-to-end metrics on the same traces

Computed with `sagate.eval.e2e_metrics` on `runs/nb01/outputs/b0_traces/traces.jsonl` (reproduces `b0_summary.json`):

| Metric | All | Banking | Workspace |
|---|---|---|---|
| Sensitive-data leakage (CONFIDENTIAL+ data sent to a lower-labelled destination) | 0/142 (0.0%) | 0/30 | 0/112 |
| Tool-selection accuracy (ground-truth calls whose function the agent tried) | 203/298 (68.1%) | 36/60 (60.0%) | 167/238 (70.2%) |
| Argument validity (attempted calls that ran without a runtime error) | 371/483 (76.8%) | 98/100 (98.0%) | 273/383 (71.3%) |

## Trace statistics

| | Value |
|---|---|
| Time per scenario | median 60 s, mean 70 s, max 287 s |
| Total agent time | 2.76 GPU-hours (≈1.4 h wall-clock on 2 GPUs) |
| Tool calls per trace | median 3, mean 3.4 |
| Tool-call parse failures | 0 in the logged scenarios |
| Proposed tool calls extracted | **483** |
| … of which state-changing (go to the gate) | **97** |
| … made after an injection was already in context | 186 |
| … matching the user task's ground truth (loose match) | 217 |
| … matching the injection task's ground truth | 11 |

State-changing proposals by tool:

| Tool | Count |
|---|---|
| `create_calendar_event` | 50 |
| `update_scheduled_transaction` | 11 |
| `create_file` | 10 |
| `share_file` | 7 |
| `send_money` | 5 |
| `append_to_file` | 5 |
| `update_password` | 4 |
| `send_email` | 3 |
| `schedule_transaction` | 2 |
| **Total** | **97** |

The most common read-only calls were `search_files_by_filename` (59), `get_day_calendar_events` (49) and
`search_files` (43).

## First attempt (`runs/nb01_run1`) — out of memory

| | First attempt | Final run |
|---|---|---|
| Errors | **33/142** (all workspace: 29 attacked, 4 benign) | 0/142 |
| Utility | 29/142 (20.4%) | 49/142 (34.5%) |
| Workspace utility | 14/112 (12.5%) | 34/112 (30.4%) |
| ASR | 9/120 (7.5%) | 10/120 (8.3%) |
| Proposals extracted | 321 | 483 |

Every error was `CUDA out of memory`, with single allocations of up to 16.8 GiB on a 14.6 GiB GPU. Workspace
file tasks build long prompts, and SDPA attention on a T4 materialises the full attention matrix. Fix (commit
`ac20d80`): prefill long prompts in 1,024-token chunks. The re-run had no errors. Banking results were identical
in both runs (greedy decoding), so the fix did not change model behaviour. **Use the final run (`runs/nb01`) for
the report.**

## Takeaways for the report

- B0 is a weak agent: it completes about a third of its tasks. Since only 10 attacks succeed end to end (8 in
  banking), there is little room to show security gains end to end, except in banking.
- Most of the security pressure in the gate's test set therefore comes from the offline cases (logged proposals from
  stronger agents plus the Qwen proposals), not from Qwen's own successful attacks.
- Only 97 of 483 Qwen proposals are state-changing, which is why the test cases were drawn mainly from the existing
  AgentDojo logs (architecture §11).
