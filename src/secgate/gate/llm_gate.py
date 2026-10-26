"""One gate class for B2–B5: a prompted gate is this class without an adapter, a learned gate the same class with a
LoRA adapter. Outputs are cached by (model, adapter, decision space, prompt), so re-runs cost nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..data.io import KeyedStore, content_key
from .decoder import EnumDecoder, ScoringBackend
from .prompts import chat_messages
from .schema import GateInput, GateOutput


class LLMGate:
    def __init__(self, backend: ScoringBackend, decision_space: Sequence[str], intermediate: bool = True,
                 adapter: str | None = None, cache_path: str | Path | None = None, cite: bool = False,
                 allow_threshold: float | None = None, name: str = "llm_gate"):
        self.backend = backend
        self.space = tuple(decision_space)
        self.intermediate = intermediate
        self.adapter = adapter
        self.cite = cite
        self.allow_threshold = allow_threshold
        self.name = name
        self.cache = KeyedStore(cache_path)
        self.decoder = EnumDecoder(backend, self.space, intermediate)

    def decide(self, gi: GateInput) -> GateOutput:
        messages = chat_messages(gi, self.space, self.intermediate)
        key = content_key(getattr(self.backend, "model_id", ""), self.adapter, self.space, self.intermediate,
                          self.cite, self.allow_threshold, messages)
        hit = self.cache.get(key)
        if hit is not None:
            return GateOutput.from_dict(hit)
        if hasattr(self.backend, "use_adapter"):
            self.backend.use_adapter(self.adapter)
        out = self.decoder.decode(messages, valid_ids=gi.evidence_ids(), cite=self.cite,
                                  allow_threshold=self.allow_threshold)
        self.cache.put(key, out.to_dict())
        return out

    def close(self) -> None:
        self.cache.close()
