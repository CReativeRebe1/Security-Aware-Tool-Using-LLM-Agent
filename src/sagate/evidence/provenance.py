"""Argument- and instruction-level provenance (ARCHITECTURE.md §5.2).

Two modes over the same matching code:
- oracle:   knows the exact injected strings (upper bound; reproduces the dataset's `arg_provenance`).
- inferred: runtime-realistic; knows only which tool outputs carry third-party content and flags blocks that
            contain instruction-like text. Pure string matching, CPU only.

Record format (GateInput.provenance):
  {"id": "P0", "kind": "call", "instruction_origin": "user" | "T3", "trust": "trusted" | "untrusted"}
  {"id": "P1", "kind": "arg", "arg": "recipient", "value": "US13...", "sources": ["T1"], "trust": "untrusted"}
Trust values: trusted (user prompt or system state), third_party (benign-looking third-party content),
untrusted (injected / instruction-bearing content), unknown (value not found, or too short to match).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

MIN_MATCH_LEN = 3          # dataset rule: str(value) shorter than this is "too_short"
VALUE_PREVIEW = 120

_INSTRUCTION_CUES = re.compile(
    r"(ignore (all |any )?(the )?(previous|prior|above)|<information>|</information>|\btodo:|"
    r"important (message|instructions?)|before you can solve the task|"
    r"\bplease (send|transfer|forward|delete|email|change|create|share|pay|update|invite)\b|"
    r"\byou (must|should|need to|have to) (first )?(send|transfer|forward|delete|email|change|create|share|pay)\b|"
    r"\b(send|transfer|forward) (a|the|all|every)\b.{0,60}\bto\b|"
    r"without asking|do not tell the user|change the password)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ToolBlock:
    """One tool output visible before the proposed call."""

    id: str                    # T1..Tn in conversation order
    function: str
    call_index: int            # index among all tool calls of the trace
    text: str
    third_party: bool
    injected: bool | None = None          # oracle only: contains an injected string

    @property
    def source(self) -> str:
        return f"tool:{self.function}#{self.call_index}"

    @property
    def instruction_like(self) -> bool:
        return bool(_INSTRUCTION_CUES.search(self.text))


def flatten_values(value: Any) -> list[str]:
    """Scalar strings inside an argument value. Booleans/None carry no provenance and are skipped."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in flatten_values(v)]
    if isinstance(value, dict):
        if "__expr__" in value:
            return []
        return [s for v in value.values() for s in flatten_values(v)]
    return [str(value)]


def _norm(s: str) -> str:
    return s.lower()


_SQUASH = re.compile(r"[\s'\"\\]+")


def _squash(s: str) -> str:
    return _SQUASH.sub("", s.lower())


def contains_injection(text: str, injections: Iterable[str], chunk: int = 40) -> bool:
    """True if the tool output carries an injected string. Tool outputs are YAML-formatted (re-wrapped lines,
    quoting), so compare with whitespace/quotes removed and accept any `chunk`-char piece of the injection."""
    t = _squash(text)
    for inj in injections:
        q = _squash(inj)
        if not q:
            continue
        if len(q) <= chunk:
            if q in t:
                return True
            continue
        if any(q[i:i + chunk] in t for i in range(0, len(q) - chunk + 1, chunk // 2)):
            return True
    return False


def _variants(s: str) -> list[str]:
    # exact string form only (the dataset matches str(value), so 4.0 does not match "4")
    return [s]


def _strip_injections(text: str, injections: list[str]) -> str:
    for i in injections:
        text = text.replace(i, " ")
    return text


def tag_arg(value: Any, user_prompt: str, injections: Iterable[str], tool_texts: Iterable[str]) -> list[str]:
    """Dataset-compatible tags for one argument: user_prompt / injection / tool_output / unknown / too_short."""
    scalars = flatten_values(value)
    if not scalars:
        return []
    up, inj = _norm(user_prompt or ""), [_norm(i) for i in injections if i]
    tools = [_strip_injections(_norm(t), inj) for t in tool_texts]   # tool_output = non-injected tool text
    tags: set[str] = set()
    for s in dict.fromkeys(scalars):
        forms = [_norm(v) for v in _variants(s)]
        if len(forms[0].strip()) < MIN_MATCH_LEN:
            tags.add("too_short")
            continue
        hit = False
        if any(f in up for f in forms):
            tags.add("user_prompt"); hit = True
        if any(f in i for i in inj for f in forms):
            tags.add("injection"); hit = True
        if any(f in t for t in tools for f in forms):
            tags.add("tool_output"); hit = True
        if not hit:
            tags.add("unknown")
    return sorted(tags)


def arg_provenance(args: dict, user_prompt: str, injections: Iterable[str], tool_texts: Iterable[str]) -> dict:
    injections, tool_texts = list(injections), list(tool_texts)
    return {k: tag_arg(v, user_prompt, injections, tool_texts) for k, v in args.items()}


def _preview(value: Any) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= VALUE_PREVIEW else s[: VALUE_PREVIEW - 1] + "…"


def build_records(
    args: dict,
    user_prompt: str,
    blocks: list[ToolBlock],
    mode: str = "oracle",
    injections: Iterable[str] = (),
    injection_goal_match: bool = False,
) -> list[dict]:
    """Provenance records for one proposed call. `injections` and `injection_goal_match` are oracle-only."""
    if mode not in ("oracle", "inferred"):
        raise ValueError(f"unknown provenance mode {mode!r}")
    injections = [i for i in injections if i]
    if mode == "oracle":
        for b in blocks:
            b.injected = contains_injection(b.text, injections)
    up = _norm(user_prompt or "")
    records: list[dict] = []
    first_untrusted: str | None = None

    for k, (name, value) in enumerate(args.items(), start=1):
        scalars = flatten_values(value)
        if not scalars:
            continue
        sources: list[str] = []
        in_prompt, matched_any, too_short = False, False, True
        for s in scalars:
            forms = [_norm(v) for v in _variants(s)]
            if len(forms[0].strip()) < MIN_MATCH_LEN:
                continue
            too_short = False
            if any(f in up for f in forms):
                in_prompt = matched_any = True
            for b in blocks:
                if any(f in _norm(b.text) for f in forms):
                    matched_any = True
                    if b.id not in sources:
                        sources.append(b.id)
        if in_prompt:
            sources.insert(0, "user_prompt")
        trust = _arg_trust(in_prompt, sources, blocks, mode, matched_any, too_short, injections, scalars)
        rec = {"id": f"P{k}", "kind": "arg", "arg": name, "value": _preview(value), "sources": sources,
               "trust": trust}
        records.append(rec)
        if trust == "untrusted" and first_untrusted is None:
            first_untrusted = next((s for s in sources if s != "user_prompt" and _block(blocks, s)
                                    and _is_untrusted_block(_block(blocks, s), mode)), None)

    origin = first_untrusted
    if origin is None and mode == "oracle" and injection_goal_match:
        origin = next((b.id for b in blocks if b.injected), None)
    call = {"id": "P0", "kind": "call", "instruction_origin": origin or "user",
            "trust": "untrusted" if origin else "trusted"}
    if origin:
        call["origin_source"] = _block(blocks, origin).source
    return [call, *records]


def _block(blocks: list[ToolBlock], bid: str) -> ToolBlock | None:
    return next((b for b in blocks if b.id == bid), None)


def _is_untrusted_block(b: ToolBlock, mode: str) -> bool:
    if mode == "oracle":
        return bool(b.injected)
    return b.third_party and b.instruction_like


def _arg_trust(in_prompt, sources, blocks, mode, matched_any, too_short, injections, scalars) -> str:
    if in_prompt:
        return "trusted"
    if too_short:
        return "unknown"
    if not matched_any:
        # oracle: the value may sit only in the injected text (e.g. injection seen in a later message)
        if mode == "oracle" and any(_norm(s) in _norm(i) for s in scalars for i in injections):
            return "untrusted"
        return "unknown"
    blks = [b for s in sources if (b := _block(blocks, s))]
    if mode == "oracle":
        injected_value = any(_norm(s) in _norm(i) for s in scalars for i in injections
                             if len(s) >= MIN_MATCH_LEN)
        if injected_value:
            return "untrusted"
    elif any(_is_untrusted_block(b, mode) for b in blks):
        return "untrusted"
    if all(not b.third_party for b in blks):
        return "trusted"
    return "third_party"


def attribution_accuracy(pred: list[dict], oracle: list[dict]) -> tuple[int, int]:
    """(#args whose trust matches the oracle, #args) — provenance attribution accuracy (§8)."""
    o = {r["arg"]: r["trust"] for r in oracle if r.get("kind") == "arg"}
    p = {r["arg"]: r["trust"] for r in pred if r.get("kind") == "arg"}
    keys = [k for k in o if o[k] != "unknown"]
    return sum(p.get(k) == o[k] for k in keys), len(keys)
