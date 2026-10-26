"""Enum-scoring constrained decoder (ARCHITECTURE.md §5.5).

All output fields are closed enums, so instead of a grammar engine the decoder teacher-forces the JSON skeleton
and, at each field, scores every allowed value (log P(value + '"' | prefix)) and takes the argmax. This gives
always-parseable output, exact class probabilities (p_allow for the B4 threshold sweep / Pareto curves) and no
extra dependencies. Generation stops after `decision` unless citations are requested.

The skeleton is byte-identical to `json.dumps(target)` (see prompts.target_text), which is also the SFT target.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, Sequence

from .schema import FIELD_VALUES, GateOutput, output_fields

_ID = re.compile(r'"((?:[A-Z]+-\d+\.\d+)|(?:P\d+)|(?:T\d+))"')


class ScoringBackend(Protocol):
    def chat_prefix(self, messages: list[dict]) -> str:
        """Prompt text including the assistant generation header (thinking disabled)."""

    def score(self, prefix: str, continuations: Sequence[str]) -> list[float]:
        """Sum of token log-probs of each continuation given the prefix."""

    def generate(self, prefix: str, max_new_tokens: int, stop: Sequence[str] = ()) -> str:
        """Greedy continuation of the prefix."""


def softmax(xs: Sequence[float]) -> list[float]:
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [v / s for v in e]


class EnumDecoder:
    def __init__(self, backend: ScoringBackend, decision_space: Sequence[str], intermediate: bool = True):
        self.backend = backend
        self.space = tuple(decision_space)
        self.fields = output_fields(intermediate)

    def decode(self, messages: list[dict], valid_ids: set[str] | None = None, cite: bool = False,
               allow_threshold: float | None = None) -> GateOutput:
        """Decode one gate output. With `allow_threshold` (binary gates, B4 sweep) the decision is ALLOW iff
        p_allow >= threshold instead of the argmax."""
        prefix = self.backend.chat_prefix(messages)
        text = "{"
        chosen: dict[str, str] = {}
        scores: dict[str, dict[str, float]] = {}
        for i, f in enumerate(self.fields):
            text += ("" if i == 0 else ", ") + f'"{f}": "'
            values = self.space if f == "decision" else FIELD_VALUES[f]
            lps = self.backend.score(prefix + text, [v + '"' for v in values])
            scores[f] = dict(zip(values, lps))
            best = values[max(range(len(values)), key=lambda k: lps[k])]
            if f == "decision" and allow_threshold is not None and "ALLOW" in values:
                p = dict(zip(values, softmax(lps)))["ALLOW"]
                best = "ALLOW" if p >= allow_threshold else max(
                    (v for v in values if v != "ALLOW"), key=lambda v: scores[f][v])
            chosen[f] = best
            text += best + '"'
        probs = dict(zip(scores["decision"].keys(), softmax(list(scores["decision"].values()))))
        cited: list[str] = []
        if cite:
            text += ', "evidence_cited": ['
            gen = self.backend.generate(prefix + text, max_new_tokens=48, stop=["]"])
            cited = [m for m in dict.fromkeys(_ID.findall(gen)) if valid_ids is None or m in valid_ids]
        return GateOutput(
            decision=chosen["decision"],
            missing_evidence=chosen.get("missing_evidence"),
            required_authority=chosen.get("required_authority"),
            evidence_cited=cited,
            p_allow=probs.get("ALLOW"),
            scores=scores,
        )
