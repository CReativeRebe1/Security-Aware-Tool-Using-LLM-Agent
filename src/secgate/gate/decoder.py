"""Enum-scoring constrained decoder.

Every generated field is a closed enum, so the decoder writes the JSON skeleton itself and, at each field, scores
every allowed value as a continuation (sum of token log-probs of `value"` given everything so far) and keeps the
best. The result is always valid JSON, and the decision field comes with exact class probabilities — `p_allow`
drives the B4 threshold sweep and the Pareto curves. Generation stops after `decision` unless citations are
requested. The skeleton is byte-identical to prompts.answer_text(), which is also the training target.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, Sequence

from .schema import FIELD_VALUES, GateOutput, output_fields

_CITE_ID = re.compile(r'"((?:[A-Z]+-\d+\.\d+)|(?:P\d+)|(?:T\d+))"')


class ScoringBackend(Protocol):
    model_id: str

    def chat_prefix(self, messages: list[dict]) -> str: ...

    def score(self, prefix: str, continuations: Sequence[str]) -> list[float]: ...

    def generate(self, prefix: str, max_new_tokens: int, stop: Sequence[str] = ()) -> str: ...


def softmax(xs: Sequence[float]) -> list[float]:
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    z = sum(e)
    return [v / z for v in e]


class EnumDecoder:
    def __init__(self, backend: ScoringBackend, decision_space: Sequence[str], intermediate: bool = True):
        self.backend = backend
        self.space = tuple(decision_space)
        self.fields = output_fields(intermediate)

    def decode(self, messages: list[dict], valid_ids: set[str] | None = None, cite: bool = False,
               allow_threshold: float | None = None) -> GateOutput:
        """With `allow_threshold` (binary gates), the decision is ALLOW iff p_allow >= threshold."""
        prefix = self.backend.chat_prefix(messages)
        text = "{"
        chosen: dict[str, str] = {}
        scores: dict[str, dict[str, float]] = {}
        p_allow = None
        for i, f in enumerate(self.fields):
            text += ("" if i == 0 else ", ") + f'"{f}": "'
            values = self.space if f == "decision" else FIELD_VALUES[f]
            lps = self.backend.score(prefix + text, [v + '"' for v in values])
            scores[f] = dict(zip(values, lps))
            best = max(values, key=lambda v: scores[f][v])
            if f == "decision":
                probs = dict(zip(values, softmax(lps)))
                p_allow = probs.get("ALLOW")
                if allow_threshold is not None and p_allow is not None:
                    others = [v for v in values if v != "ALLOW"]
                    best = "ALLOW" if p_allow >= allow_threshold else max(others, key=lambda v: probs[v])
            chosen[f] = best
            text += best + '"'
        cited: list[str] = []
        if cite:
            text += ', "evidence_cited": ['
            gen = self.backend.generate(prefix + text, max_new_tokens=48, stop=["]"])
            cited = [c for c in dict.fromkeys(_CITE_ID.findall(gen)) if valid_ids is None or c in valid_ids]
        return GateOutput(decision=chosen["decision"], missing_evidence=chosen.get("missing_evidence"),
                          required_authority=chosen.get("required_authority"), evidence_cited=cited,
                          p_allow=p_allow, scores=scores)
