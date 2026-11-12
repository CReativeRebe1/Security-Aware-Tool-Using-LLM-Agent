"""One class for B2–B5: prompted gate = no adapter, learned gate = LoRA adapter (P2)."""

from __future__ import annotations

from typing import Sequence

from .cache import GateCache
from .decoder import EnumDecoder, ScoringBackend
from .prompts import chat_messages
from .schema import GateInput, GateOutput


class LLMGate:
    def __init__(
        self,
        backend: ScoringBackend,
        decision_space: Sequence[str],
        intermediate: bool = True,
        adapter: str | None = None,
        cache: GateCache | None = None,
        cite: bool = False,
        allow_threshold: float | None = None,
        model_id: str = "",
    ):
        self.backend = backend
        self.space = tuple(decision_space)
        self.intermediate = intermediate
        self.adapter = adapter
        self.cache = cache or GateCache(None)
        self.cite = cite
        self.allow_threshold = allow_threshold
        self.model_id = model_id or getattr(backend, "model_id", "")
        self.decoder = EnumDecoder(backend, self.space, intermediate)

    def decide(self, gi: GateInput) -> GateOutput:
        messages = chat_messages(gi, self.space, self.intermediate)
        key = self.cache.key(self.model_id, self.adapter, self.space, self.intermediate, messages,
                             self.allow_threshold)
        hit = self.cache.get(key)
        if hit is not None:
            return GateOutput.from_dict(hit)
        use = getattr(self.backend, "use_adapter", None)
        if use is not None:
            use(self.adapter)
        out = self.decoder.decode(messages, valid_ids=gi.evidence_ids(), cite=self.cite,
                                  allow_threshold=self.allow_threshold)
        self.cache.put(key, out.to_dict())
        return out
