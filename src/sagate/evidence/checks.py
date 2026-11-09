"""Deterministic pre-checks on a proposed call: where a payment amount came from and whether the item already exists.

Computed from the GateInput alone (user prompt, prior calls, tool outputs), so training, offline evaluation and live
runs get the same values without rebuilding any case. The gate sees them in its CHECKS section as evidence; only the
guards in gate/guards.py act on them directly.
"""

from __future__ import annotations

import re
from typing import Any

from ..gate.schema import GateInput
from .tools_registry import spec

# A number on its own: not part of an IBAN, a date or an id.
_NUMBER = re.compile(r"(?<![\w.,-])\d[\d,]*(?:\.\d+)?(?![\w-])")
_RECORD = re.compile(r"(?m)^- ")

# The arguments that identify "the same item" per tool.
_IDENTITY_ARGS = {
    "create_calendar_event": ("title", "start_time"),
    "create_file": ("filename",),
    "send_money": ("recipient", "amount"),
    "schedule_transaction": ("recipient", "amount"),
}


def numbers(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in _NUMBER.findall(text or "")}


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def amount_source(gi: GateInput) -> str | None:
    """user | tool_content | none; None for calls that carry no numeric payment amount."""
    call = gi.proposed_call
    if spec(call["function"]).action != "transfer":
        return None
    amount = _to_float((call.get("args") or {}).get("amount"))
    if amount is None:
        return None
    said = [str(gi.user.get("prompt") or "")]
    said += [str(h.get("response") or "") for h in gi.resolution_history if h.get("kind") == "ASK_USER"]
    if any(amount in numbers(t) for t in said):
        return "user"
    if any(amount in numbers(t.get("text", "")) for t in gi.untrusted_content):
        return "tool_content"
    return "none"


def _same(a: Any, b: Any) -> bool:
    x, y = _to_float(a), _to_float(b)
    if x is not None and y is not None:
        return x == y
    return str(a).strip().lower() == str(b).strip().lower()


def _in_record(key: str, value: Any, record: str) -> bool:
    if key == "amount":
        return _to_float(value) in numbers(record)
    return str(value).strip().lower() in record.lower()


def duplicate_of(gi: GateInput) -> tuple[str, str | None] | None:
    """(prior_call | existing_record | none, block id); None for tools with no notion of a duplicate."""
    call = gi.proposed_call
    keys = _IDENTITY_ARGS.get(call["function"])
    args = call.get("args") or {}
    if keys is None or any(args.get(k) is None for k in keys):
        return None
    for p in gi.prior_calls:
        if p.get("function") == call["function"] and all(_same((p.get("args") or {}).get(k), args[k]) for k in keys):
            return "prior_call", None
    for t in gi.untrusted_content:
        for record in _RECORD.split(t.get("text", "")):
            if all(_in_record(k, args[k], record) for k in keys):
                return "existing_record", t.get("id")
    return "none", None


_ACTION_WORDS = {
    "transfer": r"pay|send|transfer|wire|settle|refund|reimburse|top[- ]?up|schedule|set up|update|change|increase|raise|adjust|repay",
    "disclose": r"send|email|mail|share|forward|reply|respond|tell|notify|invite",
    "delete": r"delete|remove|cancel|clear|clean|erase",
    "modify": r"create|write|add|append|update|edit|save|make|reschedule|move|change|draft",
    "invite": r"schedule|book|invite|add|create|set up|organi[sz]e|arrange|plan",
    "account_change": r"change|update|reset|set|edit",
}


def action_requested(gi: GateInput) -> str | None:
    """Did the user's own words ask for this kind of action? Arguments can trace to the user while the action does not."""
    action = spec(gi.proposed_call["function"]).action
    words = _ACTION_WORDS.get(action)
    if words is None:
        return None
    return "yes" if re.search(rf"\b(?:{words})", str(gi.user.get("prompt") or ""), re.IGNORECASE) else "no"


def _block_degree(gi: GateInput, source: str) -> int:
    """1 = a tool output the user's request led to directly; 2 = one reached through values found in other content."""
    block = next((t for t in gi.untrusted_content if t.get("id") == source), None)
    if block is None or "#" not in block.get("source", ""):
        return 1
    index = int(block["source"].rsplit("#", 1)[1])
    if index >= len(gi.prior_calls):
        return 1
    prompt = str(gi.user.get("prompt") or "").lower()
    values = [str(v).lower() for v in (gi.prior_calls[index].get("args") or {}).values() if isinstance(v, str) and len(v) >= 3]
    if not values or any(v in prompt for v in values):
        return 1
    others = [t.get("text", "").lower() for t in gi.untrusted_content if t.get("id") != source]
    return 2 if any(v in o for v in values for o in others) else 1


def trust_degree(gi: GateInput) -> str | None:
    """Worst distance from the user's command over the authority-bearing arguments: 0, 1, 2 or unknown."""
    if gi.provenance is None:
        return None
    content = set(spec(gi.proposed_call["function"]).content_args)
    degrees: list[int] = []
    for r in gi.provenance:
        if r.get("kind") != "arg" or r.get("arg") in content:
            continue
        if r.get("trust") == "trusted":
            degrees.append(0)
        elif r.get("trust") == "unknown":
            continue
        else:
            degrees.append(max((_block_degree(gi, s) for s in r.get("sources", []) if s != "user_prompt"), default=1))
    return str(max(degrees)) if degrees else "unknown"


def run_checks(gi: GateInput, amount: bool = True, duplicate: bool = True, degree: bool = True) -> dict | None:
    out: dict[str, str] = {}
    if amount and (source := amount_source(gi)):
        out["amount_source"] = source
    if duplicate and (found := duplicate_of(gi)):
        out["duplicate"] = found[0]
        if found[1]:
            out["duplicate_ref"] = found[1]
    if degree:
        if (d := trust_degree(gi)) is not None:
            out["trust_degree"] = d
        if (a := action_requested(gi)) is not None:
            out["action_requested"] = a
    return out or None
