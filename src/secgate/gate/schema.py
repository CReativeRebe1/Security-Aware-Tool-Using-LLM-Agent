"""Data contracts shared by every gate, the evaluator and (later) the trainer.

Label vocabularies are frozen together with docs/ANNOTATION_GUIDE.md.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

DECISIONS = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
MISSING_EVIDENCE = ("none", "user_intent", "recipient_identity", "resource_target", "approval",
                    "data_classification")
REQUIRED_AUTHORITY = ("none", "current_user", "resource_owner", "manager", "security_admin")
LABELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
TRUST_LEVELS = ("user", "system", "third_party", "untrusted", "unknown")

DEFERRALS = frozenset({"ASK_USER", "ESCALATE"})
FINAL = frozenset({"ALLOW", "BLOCK"})

# Generated fields, in order. The intermediate fields come first so they act as structured reasoning.
INTERMEDIATE_FIELDS = ("missing_evidence", "required_authority")
FIELD_VALUES: dict[str, tuple[str, ...]] = {
    "missing_evidence": MISSING_EVIDENCE,
    "required_authority": REQUIRED_AUTHORITY,
    "decision": DECISIONS,
}


def output_fields(intermediate: bool) -> tuple[str, ...]:
    return (*INTERMEDIATE_FIELDS, "decision") if intermediate else ("decision",)


def label_rank(label: str | None) -> int:
    return LABELS.index(label) if label in LABELS else -1


def to_binary(decision: str) -> str:
    """Binary projection: a deferral does not execute, so it counts as BLOCK."""
    return "ALLOW" if decision == "ALLOW" else "BLOCK"


def restrict(decision: str, space: Iterable[str], final_action: str | None = None) -> str:
    """Map a decision into a smaller decision space: a removed class becomes `final_action` when that is in the
    space, otherwise BLOCK."""
    space = set(space)
    if decision in space:
        return decision
    return final_action if final_action in space else "BLOCK"


@dataclass
class GateInput:
    """Everything a gate sees for one proposed tool call. A field set to None was removed by an evidence ablation;
    renderers and rules treat None as absent (not as empty)."""

    case_id: str
    suite: str
    request: dict                                  # {principal, prompt}
    action: dict                                   # {function, args, action_class, state_changing}
    prior_calls: list = field(default_factory=list)
    provenance: dict | None = field(default_factory=dict)    # {origin: {...}, args: [{...}]}
    authority: dict | None = field(default_factory=dict)
    sensitivity: dict | None = field(default_factory=dict)
    policy: list | None = field(default_factory=list)        # retrieved handbook clauses
    content: list = field(default_factory=list)              # tool outputs, rendered as untrusted data
    resolution: list = field(default_factory=list)           # answered ASK_USER / ESCALATE rounds

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GateInput":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: copy.deepcopy(v) for k, v in d.items() if k in names})

    def copy(self) -> "GateInput":
        return GateInput.from_dict(self.to_dict())

    def evidence_ids(self) -> set[str]:
        """Ids a gate may cite: provenance records, policy clauses and content blocks."""
        ids = {c["id"] for c in self.content}
        ids |= {c["id"] for c in self.policy or []}
        if self.provenance:
            ids.add(self.provenance["origin"]["id"])
            ids |= {r["id"] for r in self.provenance.get("args", [])}
        return ids


@dataclass
class GateOutput:
    decision: str
    missing_evidence: str | None = None
    required_authority: str | None = None
    evidence_cited: list = field(default_factory=list)
    p_allow: float | None = None
    scores: dict = field(default_factory=dict)      # field -> {value: log-prob} (diagnostics)

    def __post_init__(self) -> None:
        for name in ("decision", *INTERMEDIATE_FIELDS):
            v = getattr(self, name)
            if v is not None and v not in FIELD_VALUES[name]:
                raise ValueError(f"invalid {name} {v!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GateOutput":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in names})

    def answer(self, intermediate: bool = True, with_citations: bool = False) -> dict[str, Any]:
        """The JSON object a gate generates, in field order (SFT target and decoder skeleton)."""
        out: dict[str, Any] = {f: getattr(self, f) for f in output_fields(intermediate)}
        if with_citations:
            out["evidence_cited"] = list(self.evidence_cited)
        return out
