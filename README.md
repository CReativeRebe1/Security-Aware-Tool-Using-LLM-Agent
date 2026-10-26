# Security-Aware Tool-Using LLM Agent

**Provenance- and authority-aware resolution of tool actions at runtime**

CL3410 · Language Models and Agents · IIIT Hyderabad · Monsoon 2026 · Group project (team Autobots)

## What this project is

Tool-using LLM agents send emails, move files and make payments. A proposed tool call can be unsafe because the
instruction came from untrusted content (prompt injection), the requester lacks authority over the action, or
sensitive data is flowing somewhere it shouldn't.

We build a **runtime security gate** that sits between the agent and its tools. For every proposed tool call it
combines provenance, authority, resource sensitivity and policy evidence, then decides:

| Decision | Meaning |
| --- | --- |
| `ALLOW` | Enough trusted evidence; the action is authorized |
| `BLOCK` | Evidence is sufficient and the action is prohibited |
| `ASK_USER` | Evidence is missing and the current user can legitimately supply it |
| `ESCALATE` | Stronger authority (e.g. a manager) is required |

ASK_USER and ESCALATE collect one new piece of evidence and re-run the same gate (max 2 rounds; unresolved → BLOCK).

## Research questions

- **RQ1 — Evidence:** does provenance and authority evidence reduce unauthorized actions and unnecessary deferrals?
- **RQ2 — Resolution space:** with the same model, traces and evidence, does a four-way gate beat the same learned
  gate restricted to ALLOW / BLOCK once interaction cost is charged?

## Setup

| | |
| --- | --- |
| Environment | AgentDojo `workspace` + `banking` suites, split by scenario into train-source / test-source pools |
| Models | Qwen3-8B, 4-bit, thinking off — task agent and gate |
| Gates | B0 no gate · B1 rules · B2/B3 prompted binary/four-way · B4/B5 QLoRA binary/four-way |
| Test set | ~240 human-labelled cases, two independent annotators, Krippendorff's α |
| Success region | Unauthorized-action rate ≤ 5% and unnecessary-deferral rate ≤ 10% |

## Branches

| Branch | Contents |
| --- | --- |
| `main` | Project overview (this file) |
| `dataset` | Processed AgentDojo data, splits and dataset documentation |

## Team

| Member | Roll no. |
| --- | --- |
| Yogendra Patel | 2025201098 |
| Rinkesh Verma | 2025201070 |
| Shubham Kumar Sunny | 2025201025 |
| Prabhash Padhan | 2025201089 |
