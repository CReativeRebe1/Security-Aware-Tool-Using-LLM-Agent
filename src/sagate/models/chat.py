"""Qwen3 chat helpers: AgentDojo messages <-> HF chat messages, tool schemas, and <tool_call> parsing."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ..data.loaders import message_text

_TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)


def _fc_dict(tc: Any) -> dict:
    if isinstance(tc, dict):
        return tc
    return {"function": tc.function, "args": dict(tc.args), "id": getattr(tc, "id", None)}


def to_hf_messages(messages: Iterable[dict]) -> list[dict]:
    """AgentDojo ChatMessages -> messages for tokenizer.apply_chat_template (Qwen3 tool format)."""
    out = []
    for m in messages:
        role = m["role"]
        if role == "assistant":
            msg = {"role": "assistant", "content": message_text(m)}
            calls = [_fc_dict(tc) for tc in (m.get("tool_calls") or [])]
            if calls:
                msg["content"] = strip_tool_calls(msg["content"])
                msg["tool_calls"] = [{"type": "function", "function": {"name": c["function"], "arguments": c["args"]}}
                                     for c in calls]
            out.append(msg)
        elif role == "tool":
            text = message_text(m)
            if m.get("error"):
                text = f"{text}\nError: {m['error']}".strip()
            out.append({"role": "tool", "content": text})
        else:
            out.append({"role": role, "content": message_text(m)})
    return out


def tool_schemas(functions: Iterable[Any]) -> list[dict]:
    """AgentDojo Function objects -> OpenAI-style tool schemas (what Qwen3's chat template expects)."""
    out = []
    for f in functions:
        params = f.parameters.model_json_schema()
        params.pop("title", None)
        out.append({"type": "function",
                    "function": {"name": f.name, "description": f.description, "parameters": params}})
    return out


def strip_tool_calls(text: str) -> str:
    return _TOOL_CALL.sub("", text or "").strip()


def parse_tool_calls(text: str) -> tuple[str, list[dict], str | None]:
    """Return (content without tool-call blocks, [{function, args}], error or None)."""
    calls, err = [], None
    for raw in _TOOL_CALL.findall(text or ""):
        try:
            obj = json.loads(raw)
            name = obj["name"]
            args = obj.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args) if args.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments is not an object")
            calls.append({"function": str(name), "args": args})
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
    return strip_tool_calls(text), calls, err
