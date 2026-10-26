"""Does a proposed call match one of a task's ground-truth calls?

Same function, and every *distinctive* static argument (recipient addresses, IBANs, ids, file names, passwords)
equal; if the ground-truth call has no distinctive argument, the function alone decides. Amounts, dates and free
text are ignored because agents legitimately vary them. Used for analysis, the scenario responder and B0 proposal
extraction — never as a gold label.
"""

from __future__ import annotations

import re
from typing import Any

_DISTINCT_KEYS = {"recipients", "recipient", "email", "participants", "file_id", "email_id", "event_id", "id",
                  "filename", "file_path", "password", "cc", "bcc"}
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")


def _norm(v: Any):
    if isinstance(v, (list, tuple)):
        return frozenset(str(x).strip().lower() for x in v)
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v).strip().lower()


def _static(v: Any) -> bool:
    if isinstance(v, dict) and "__expr__" in v:
        return False
    if isinstance(v, (list, tuple)):
        return all(_static(x) for x in v)
    return True


def _distinctive(key: str, v: Any) -> bool:
    if key in _DISTINCT_KEYS:
        return True
    return isinstance(v, str) and (bool(_IBAN.match(v)) or "@" in v)


def call_matches(call: dict, gt_call: dict) -> bool:
    if call.get("function") != gt_call.get("function"):
        return False
    args = call.get("args") or {}
    keys = [k for k, v in (gt_call.get("args") or {}).items() if _static(v) and _distinctive(k, v)]
    return all(k in args and _norm(args[k]) == _norm(gt_call["args"][k]) for k in keys)


def matches_task(call: dict, task: dict | None) -> bool:
    if not task:
        return False
    return any(call_matches(call, gt) for gt in task.get("ground_truth_calls") or [])
