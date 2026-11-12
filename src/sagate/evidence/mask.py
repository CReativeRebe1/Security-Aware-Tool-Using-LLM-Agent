"""EvidenceMask: the feeder that decides what evidence a gate is given, identically in training and inference (P3).

Every toggle comes from the condition file (`evidence:` block). Besides removing whole fields it controls pre-answered
rounds (`history`), how policy clauses are retrieved (`rag_query`) and the computed checks.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from ..config import Condition, load_config
from ..gate.schema import GateInput
from .checks import run_checks
from .policy_index import rank as index_rank
from .policy_rag import PolicyRetriever, build_query, evidence_words


@lru_cache(maxsize=None)
def _retriever(suite: str) -> PolicyRetriever:
    return PolicyRetriever(load_config().resources_dir / "handbooks" / f"{suite}.md")


@lru_cache(maxsize=None)
def _rag_k() -> int:
    return int(load_config()["context"].get("rag_k", 5))


def retrieve_clauses(gi: GateInput, k: int | None = None) -> list[dict]:
    """Policy clauses for one call, from the evidence this gate may see: masked authority or provenance cannot
    steer the query or the index, so no ablation gets them back through the clauses. BM25 and the fact index
    (evidence/policy_index.py) are fused by reciprocal rank; without an index this is plain BM25."""
    retriever = _retriever(gi.suite)
    call = gi.proposed_call
    query = build_query(gi.user.get("prompt") or "", call["function"], call.get("action") or "", gi.authority,
                        gi.sensitivity) + " " + evidence_words(gi)
    score: Counter = Counter()
    for ranking in ([c.id for c in retriever.retrieve(query, k=len(retriever.clauses))], index_rank(gi)):
        for i, cid in enumerate(ranking):
            score[cid] += 1 / (10 + i)
    return [retriever.by_id(cid).as_dict() for cid, _ in score.most_common() if retriever.by_id(cid)][:k or _rag_k()]


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
    history: str = "full"          # full | answers_only | none | in_space (pre-answered rounds in the case, not the live loop)
    amount_source: bool = True
    duplicate_check: bool = True
    trust_degree: bool = True
    space: tuple = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")

    @classmethod
    def from_condition(cls, cond: Condition) -> "EvidenceMask":
        return cls(cond.provenance, cond.authority, cond.sensitivity, cond.rag, cond.history,
                   cond.amount_source, cond.duplicate_check, cond.trust_degree, tuple(cond.decision_space))

    def skips(self, gi: GateInput) -> bool:
        """A pre-answered case means nothing to a condition that may not see the answer: it is neither trained nor scored."""
        if self.history == "in_space":       # an earlier round of a decision this condition cannot make never happens
            return any(h.get("kind") not in self.space for h in gi.resolution_history)
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
        if self.history == "none":
            out.resolution_history = []
        elif self.history == "answers_only":
            out.resolution_history = [_answer_only(h) for h in out.resolution_history]
        out.policy_clauses = retrieve_clauses(out) if self.rag else None
        # amount_source says where a value came from, so it is provenance evidence and leaves with it
        out.checks = run_checks(out, self.amount_source and self.provenance != "none", self.duplicate_check,
                                self.trust_degree)
        return out
