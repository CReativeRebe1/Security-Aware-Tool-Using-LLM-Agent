"""Evidence ablations, applied identically in training and at inference so a gate never sees an input format it
was not trained on."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Condition
from ..gate.schema import GateInput


@dataclass(frozen=True)
class EvidenceMask:
    provenance: str = "oracle"      # oracle | inferred | none
    authority: bool = True
    sensitivity: bool = True
    rag: bool = True

    @classmethod
    def for_condition(cls, cond: Condition) -> "EvidenceMask":
        return cls(cond.provenance, cond.authority, cond.sensitivity, cond.rag)

    def apply(self, gi: GateInput, alt_provenance: dict | None = None) -> GateInput:
        """Masked copy. Inferred provenance is taken from `alt_provenance["inferred"]`."""
        out = gi.copy()
        if self.provenance == "none":
            out.provenance = None
        elif self.provenance == "inferred":
            if not alt_provenance or "inferred" not in alt_provenance:
                raise KeyError(f"{gi.case_id}: no inferred provenance stored")
            out.provenance = alt_provenance["inferred"]
        if not self.authority:
            out.authority = None
        if not self.sensitivity:
            out.sensitivity = None
        if not self.rag:
            out.policy = None
        return out
