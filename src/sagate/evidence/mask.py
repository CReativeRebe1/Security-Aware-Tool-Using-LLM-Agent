"""EvidenceMask: the feeder that decides what evidence a gate is given, identically in training and inference (P3).

Every toggle comes from the condition file (`evidence:` block). Besides removing whole fields it controls pre-answered
rounds (`history`), how policy clauses are retrieved (`rag_query`) and the computed checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..config import Condition, load_config
from ..gate.schema import GateInput
from .checks import run_checks
from .policy_rag import PolicyRetriever, build_query


@lru_cache(maxsize=None)
def _retriever(suite: str) -> PolicyRetriever:
    return PolicyRetriever(load_config().resources_dir / "handbooks" / f"{suite}.md")


def _answer_only(entry: dict) -> dict:
    """A resolution round without anything that names the required authority."""
    out = {k: v for k, v in entry.items() if k != "asked"}
    if entry.get("kind") == "ESCALATE":
        out["responder"] = "approver"
    return out


@dataclass(frozen=True)
class EvidenceMask:
    provenance: str = "oracle"     # oracle | inferred | none
    authority: bool = True
    sensitivity: bool = True
    rag: bool = True
    rag_query: str = "full"        # full | no_authority (retrieve as if the authority facts were unknown)
    history: str = "full"          # full | answers_only | none (pre-answered rounds in the case, not the live loop)
    amount_source: bool = True
    duplicate_check: bool = True
    trust_degree: bool = True

    @classmethod
    def from_condition(cls, cond: Condition) -> "EvidenceMask":
        return cls(cond.provenance, cond.authority, cond.sensitivity, cond.rag, cond.rag_query, cond.history,
                   cond.amount_source, cond.duplicate_check, cond.trust_degree)

    def skips(self, gi: GateInput) -> bool:
        """A pre-answered case means nothing to a condition that may not see the answer: it is neither trained nor scored."""
        return self.history == "none" and bool(gi.resolution_history)

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
        elif self.rag_query == "no_authority":
            call = gi.proposed_call
            query = build_query(gi.user.get("prompt") or "", call["function"], call.get("action") or "", None,
                                out.sensitivity)
            k = len(gi.policy_clauses or []) or 3
            out.policy_clauses = [c.as_dict() for c in _retriever(gi.suite).retrieve(query, k=k)]
        if self.history == "none":
            out.resolution_history = []
        elif self.history == "answers_only":
            out.resolution_history = [_answer_only(h) for h in out.resolution_history]
        # amount_source says where a value came from, so it is provenance evidence and leaves with it
        out.checks = run_checks(out, self.amount_source and self.provenance != "none", self.duplicate_check,
                                self.trust_degree)
        return out
