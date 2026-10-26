"""Provenance of a proposed tool call: who asked for the action, and where each argument value came from.

Two modes share the matching code:
  oracle    knows the exact injected strings (upper bound, mirrors the dataset's `arg_provenance`);
  inferred  runtime-realistic: knows only which tool outputs carry third-party text and looks for instruction-like
            passages in them. No knowledge of what was injected.

Output (GateInput.provenance):
  {"origin": {"id": "P0", "instruction_origin": "user" | "T2", "source": "tool:read_file#0", "trust": ...},
   "args":   [{"id": "P1", "arg": "recipient", "value": "US13...", "sources": ["T1"], "trust": ...}, ...]}
Trust: user (from the request) | system (from the user's own account state) | third_party (from content written by
someone else) | untrusted (from an instruction inside content) | unknown (not found / too short to match).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

MIN_VALUE_LEN = 3
PREVIEW_CHARS = 120
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

# Imperative, assistant-directed phrasing typical of injected instructions.
_CUES = re.compile(
    r"(ignore (all |any )?(the |your )?(previous|prior|above|earlier)"
    r"|<\s*/?\s*information\s*>|\btodo\s*:|important (message|instruction)"
    r"|before you (can )?(solve|complete|finish|do) (the|this|your) task"
    r"|(this is|message from) (me,? )?emma"
    r"|(you|assistant),? (must|should|need to|have to) (first |now |also )?"
    r"(send|transfer|forward|delete|email|change|create|share|pay|update|invite|remove)"
    r"|\bplease (send|transfer|forward|delete|email|change|create|share|pay|update|invite|remove)\b"
    r"|without (asking|telling|informing) (me|the user)"
    r"|(do not|don't) (tell|inform|mention)"
    r"|fill (them|it) in without asking)",
    re.IGNORECASE,
)

# Words that show the user's request covers an action class (used by inferred origin attribution).
ACTION_WORDS = {
    "disclose": ("send", "email", "mail", "forward", "reply", "share", "tell", "notify", "message", "inform"),
    "transfer": ("pay", "send", "transfer", "refund", "money", "payment", "rent", "bill", "schedule", "standing",
                 "transaction", "difference"),
    "delete": ("delete", "remove", "clean", "cancel", "clear", "trash"),
    "invite": ("invite", "event", "meeting", "calendar", "schedule", "lunch", "add", "participant", "create"),
    "modify": ("create", "add", "append", "write", "update", "edit", "reschedule", "move", "file", "list",
               "suggest", "change"),
    "account_change": ("password", "update", "change", "address", "info", "information", "details"),
}


@dataclass
class ContentBlock:
    """One tool output visible before the proposed call."""

    id: str                         # T1..Tn in conversation order
    function: str
    call_index: int
    text: str
    third_party: bool
    injected: bool | None = None    # oracle only

    @property
    def source(self) -> str:
        return f"tool:{self.function}#{self.call_index}"

    @property
    def instruction_like(self) -> bool:
        return bool(_CUES.search(self.text))


# --- matching helpers ---------------------------------------------------------------------------------------

def norm(text: str) -> str:
    return _WS.sub(" ", str(text).lower()).strip()


def squash(text: str) -> str:
    return _NON_ALNUM.sub("", str(text).lower())


def scalars(value: Any) -> list[str]:
    """String forms of the scalar leaves of an argument value (booleans and None carry no provenance)."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in scalars(v)]
    if isinstance(value, dict):
        if "__expr__" in value:
            return []
        return [s for v in value.values() for s in scalars(v)]
    return [str(value)]


def value_forms(s: str) -> list[str]:
    """Normalised forms of a scalar; numbers also match their usual written variants (98.7 ~ 98.70)."""
    forms = [norm(s)]
    try:
        x = float(s)
    except ValueError:
        return forms
    if x == int(x):
        forms += [str(int(x)), f"{int(x):,}", f"{x:.2f}"]
    else:
        forms += [f"{x:.2f}", f"{x:g}"]
    return list(dict.fromkeys(f for f in forms if len(f) >= MIN_VALUE_LEN))


def contains_injection(text: str, injections: Iterable[str], window: int = 32) -> bool:
    """Does a tool output carry one of the injected strings? Tool outputs are YAML-formatted (re-wrapped lines,
    quoting), so compare alphanumerics only and accept any window-sized piece of the injection."""
    t = squash(text)
    for inj in injections:
        q = squash(inj)
        if not q:
            continue
        if len(q) <= window:
            if q in t:
                return True
        elif any(q[i:i + window] in t for i in range(0, len(q) - window + 1, window // 2)):
            return True
    return False


def _in_any(forms: Sequence[str], texts: Iterable[str]) -> bool:
    return any(f in t for t in texts for f in forms)


def _preview(value: Any) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= PREVIEW_CHARS else s[: PREVIEW_CHARS - 1] + "…"


# --- dataset-compatible tags (used to check agreement with the shipped arg_provenance) ----------------------

def dataset_tags(value: Any, user_prompt: str, injections: Sequence[str], tool_texts: Sequence[str]) -> list[str]:
    """Tags in the dataset's vocabulary: user_prompt / injection / tool_output / unknown / too_short."""
    vals = scalars(value)
    if not vals:
        return []
    prompt, inj = norm(user_prompt or ""), [norm(i) for i in injections if i]
    tools = []
    for t in tool_texts:
        t = norm(t)
        for i in inj:
            t = t.replace(i, " ")
        tools.append(t)
    tags = set()
    for s in dict.fromkeys(vals):
        f = norm(s)
        if len(f) < MIN_VALUE_LEN:
            tags.add("too_short")
            continue
        hit = False
        for name, texts in (("user_prompt", [prompt]), ("injection", inj), ("tool_output", tools)):
            if any(f in t for t in texts):
                tags.add(name)
                hit = True
        if not hit:
            tags.add("unknown")
    return sorted(tags)


# --- provenance records -----------------------------------------------------------------------------------

def _block_is_untrusted(b: ContentBlock, mode: str) -> bool:
    return bool(b.injected) if mode == "oracle" else (b.third_party and b.instruction_like)


def _arg_trust(vals: list[str], prompt: str, found_in: list[ContentBlock], mode: str,
               injections: list[str]) -> str:
    forms = [f for s in vals for f in value_forms(s)]
    if not forms:
        return "unknown"
    if _in_any(forms, [prompt]):
        return "user"
    if mode == "oracle":
        inj = [norm(i) for i in injections]
        in_injection = _in_any(forms, inj)
        # text of each block with the injected strings cut out: is the value also in ordinary content?
        clean = []
        for b in found_in:
            t = norm(b.text)
            for i in inj:
                t = t.replace(i, " ")
            clean.append((b, t))
        elsewhere = [b for b, t in clean if _in_any(forms, [t])]
        if in_injection and not elsewhere:
            return "untrusted"
        found_in = elsewhere if in_injection else found_in
    else:
        if found_in and all(_block_is_untrusted(b, mode) for b in found_in):
            return "untrusted"
    if not found_in:
        return "unknown"
    if any(not b.third_party for b in found_in):
        return "system"
    return "third_party"


def _request_covers(prompt: str, action_class: str) -> bool:
    words = set(re.findall(r"[a-z]+", prompt.lower()))
    return any(w in words for w in ACTION_WORDS.get(action_class, ()))


def build_provenance(
    args: dict,
    user_prompt: str,
    blocks: list[ContentBlock],
    action_class: str,
    mode: str = "oracle",
    injections: Iterable[str] = (),
    goal_match: bool = False,
) -> dict:
    """Provenance for one proposed call.

    oracle:   `injections` are the injected strings of the scenario; `goal_match` says the call matches the
              attacker's goal, so the action itself originates in the injection.
    inferred: neither is used; the instruction is attributed to a third-party block when that block contains
              instruction-like text and the user's request does not cover the action, or when a critical value
              was copied only from such a block."""
    if mode not in ("oracle", "inferred"):
        raise ValueError(f"unknown provenance mode {mode!r}")
    injections = [i for i in injections if i] if mode == "oracle" else []
    for b in blocks:
        b.injected = contains_injection(b.text, injections) if mode == "oracle" else None
    prompt = norm(user_prompt or "")

    records = []
    for k, (name, value) in enumerate(args.items(), start=1):
        vals = scalars(value)
        if not vals:
            continue
        forms = [f for s in vals for f in value_forms(s)]
        found_in = [b for b in blocks if forms and _in_any(forms, [norm(b.text)])]
        sources = (["user"] if forms and _in_any(forms, [prompt]) else []) + [b.id for b in found_in]
        records.append({"id": f"P{k}", "arg": name, "value": _preview(value), "sources": sources,
                        "trust": _arg_trust(vals, prompt, found_in, mode, injections)})

    origin_block = None
    untrusted_blocks = [b for b in blocks if _block_is_untrusted(b, mode)]
    if mode == "oracle":
        if goal_match and untrusted_blocks:
            origin_block = untrusted_blocks[0]
    else:
        copied = [r for r in records if r["trust"] == "untrusted"]
        if copied:
            origin_block = next(b for b in blocks if b.id in copied[0]["sources"])
        elif untrusted_blocks and not _request_covers(prompt, action_class):
            origin_block = untrusted_blocks[-1]
    origin = {"id": "P0", "instruction_origin": origin_block.id if origin_block else "user",
              "trust": "untrusted" if origin_block else "user"}
    if origin_block:
        origin["source"] = origin_block.source
    return {"origin": origin, "args": records}


def attribution_accuracy(inferred: dict, oracle: dict) -> tuple[int, int]:
    """(# argument trust labels and origins that agree with the oracle, # compared)."""
    o = {r["arg"]: r["trust"] for r in oracle["args"] if r["trust"] != "unknown"}
    p = {r["arg"]: r["trust"] for r in inferred["args"]}
    hits = sum(p.get(a) == t for a, t in o.items())
    hits += inferred["origin"]["trust"] == oracle["origin"]["trust"]
    return hits, len(o) + 1
