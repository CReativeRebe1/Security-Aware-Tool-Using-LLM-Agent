"""EvidenceMask: removes evidence fields for ablations, identically in training and inference (P3)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Condition
from ..gate.schema import GateInput


@dataclass(frozen=True)
class EvidenceMask:
    provenance: str = "oracle"     # oracle | inferred | none
    authority: bool = True
    sensitivity: bool = True
    rag: bool = True

    @classmethod
    def from_condition(cls, cond: Condition) -> "EvidenceMask":
        return cls(cond.provenance, cond.authority, cond.sensitivity, cond.rag)

    def apply(self, gi: GateInput, alt_provenance: dict | None = None) -> GateInput:
        """Return a masked copy. Inferred provenance is swapped in from `alt_provenance["inferred"]`."""
        out = gi.copy()
        if self.provenance == "none":
            out.provenance = None
        elif self.provenance == "inferred":
            if not alt_provenance or "inferred" not in alt_provenance:
                raise KeyError(f"case {gi.case_id} has no inferred provenance")
            out.provenance = alt_provenance["inferred"]
        if not self.authority:
            out.authority = None
        if not self.sensitivity:
            out.sensitivity = None
        if not self.rag:
            out.policy_clauses = None
        return out
