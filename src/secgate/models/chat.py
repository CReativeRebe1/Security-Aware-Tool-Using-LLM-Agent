"""Qwen3 chat helpers: AgentDojo messages -> HF chat messages, tool schemas, and parsing of Qwen3 tool calls.

Qwen3 emits tool calls as
    <tool_call>
    {"name": "send_money", "arguments": {...}}
    </tool_call>
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ..data.loaders import message_text

_TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _call_parts(tc: Any) -> tuple[str, dict]:
    if isinstance(tc, dict):
        return tc.get("function") or tc.get("name"), tc.get("args") or tc.get("arguments") or {}
    return getattr(tc, "function"), dict(getattr(tc, "args", {}) or {})


def to_hf_messages(messages: Iterable[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m["role"]
        if role in ("system", "user"):
            out.append({"role": role, "content": message_text(m)})
        elif role == "assistant":
            msg = {"role": "assistant", "content": message_text(m)}
            calls = m.get("tool_calls") or []
            if calls:
                msg["tool_calls"] = [{"type": "function", "function": {"name": f, "arguments": a}}
                                     for f, a in map(_call_parts, calls)]
            out.append(msg)
        elif role == "tool":
            text = message_text(m)
            if m.get("error"):
                text = f"{text}\nError: {m['error']}".strip()
            out.append({"role": "tool", "content": text})
    return out


def tool_schemas(functions: Iterable[Any]) -> list[dict]:
    """OpenAI-style tool schemas from AgentDojo Function objects (pydantic parameter models)."""
    out = []
    for f in functions:
        params = f.parameters.model_json_schema() if hasattr(f.parameters, "model_json_schema") else dict(f.parameters)
        params.pop("title", None)
        out.append({"type": "function", "function": {"name": f.name, "description": f.description,
                                                     "parameters": params}})
    return out


def parse_tool_calls(raw: str) -> tuple[str, list[dict], str | None]:
    """(visible text, [{"function", "args"}], error or None)."""
    raw = _THINK.sub("", raw)
    calls, err = [], None
    for body in _TOOL_CALL.findall(raw):
        try:
            obj = json.loads(_FENCE.sub("", body.strip()))
        except json.JSONDecodeError as e:
            err = f"invalid JSON in <tool_call>: {e.msg}"
            continue
        name = obj.get("name") if isinstance(obj, dict) else None
        args = obj.get("arguments", {}) if isinstance(obj, dict) else None
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                err = "arguments must be a JSON object"
                continue
        if not name or not isinstance(args, dict):
            err = 'a tool call needs "name" and an "arguments" object'
            continue
        calls.append({"function": name, "args": args})
    if "<tool_call>" in raw and not calls and err is None:
        err = "unterminated <tool_call>"
    text = _TOOL_CALL.sub("", raw).replace("<tool_call>", "").strip()
    return text, calls, err
