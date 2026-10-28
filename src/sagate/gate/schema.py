"""Data contracts shared by every gate, the trainer and the evaluator (ARCHITECTURE.md §4)."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class Decision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ASK_USER = "ASK_USER"
    ESCALATE = "ESCALATE"


class MissingEvidence(str, Enum):
    NONE = "none"
    USER_INTENT = "user_intent"
    RECIPIENT_IDENTITY = "recipient_identity"
    RESOURCE_TARGET = "resource_target"
    APPROVAL = "approval"
    DATA_CLASSIFICATION = "data_classification"


class RequiredAuthority(str, Enum):
    NONE = "none"
    CURRENT_USER = "current_user"
    RESOURCE_OWNER = "resource_owner"
    MANAGER = "manager"
    SECURITY_ADMIN = "security_admin"


DEFERRALS = {Decision.ASK_USER.value, Decision.ESCALATE.value}
FINAL = {Decision.ALLOW.value, Decision.BLOCK.value}
LABEL_ORDER = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]

# Output fields in generation order. Intermediate fields come before `decision` (structured reasoning);
# conditions without intermediate supervision generate `decision` only.
INTERMEDIATE_FIELDS = ("missing_evidence", "required_authority")
FIELD_VALUES: dict[str, tuple[str, ...]] = {
    "missing_evidence": tuple(m.value for m in MissingEvidence),
    "required_authority": tuple(r.value for r in RequiredAuthority),
    "decision": tuple(d.value for d in Decision),
}


def output_fields(intermediate: bool) -> tuple[str, ...]:
    return (*INTERMEDIATE_FIELDS, "decision") if intermediate else ("decision",)


def project_binary(decision: str) -> str:
    """Binary projection used to score four-way outputs as ALLOW/BLOCK (a deferral does not execute)."""
    return "ALLOW" if decision == "ALLOW" else "BLOCK"


def collapse_decision(decision: str, space: Iterable[str], final_action: str | None = None) -> str:
    """Map a four-way label into a smaller decision space.

    Removed classes map to `final_action` (the gold final ALLOW/BLOCK, ARCHITECTURE.md §6) when given,
    otherwise to BLOCK.
    """
    space = set(space)
    if decision in space:
        return decision
    if final_action in space:
        return final_action
    return "BLOCK"


@dataclass
class GateInput:
    """The single input format for every gate, in training and evaluation (ARCHITECTURE.md §4.1).

    A field set to None was removed by EvidenceMask; the renderer and the rules must treat it as absent.
    """

    case_id: str
    suite: str
    user: dict                                   # {principal_id, prompt}
    proposed_call: dict                          # {function, args, state_changing, action}
    prior_calls: list = field(default_factory=list)
    provenance: list | None = field(default_factory=list)
    authority: dict | None = field(default_factory=dict)
    sensitivity: dict | None = field(default_factory=dict)
    policy_clauses: list | None = field(default_factory=list)
    untrusted_content: list = field(default_factory=list)
    resolution_history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GateInput":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: copy.deepcopy(v) for k, v in d.items() if k in names})

    def copy(self) -> "GateInput":
        return GateInput.from_dict(self.to_dict())

    def evidence_ids(self) -> set[str]:
        ids = {p["id"] for p in self.provenance or []}
        ids |= {c["id"] for c in self.policy_clauses or []}
        ids |= {t["id"] for t in self.untrusted_content}
        return ids


@dataclass
class GateOutput:
    decision: str
    missing_evidence: str | None = None
    required_authority: str | None = None
    evidence_cited: list = field(default_factory=list)
    p_allow: float | None = None
    scores: dict = field(default_factory=dict)       # field -> {value: log-prob}; decoder diagnostics

    def __post_init__(self) -> None:
        if self.decision not in FIELD_VALUES["decision"]:
            raise ValueError(f"invalid decision {self.decision!r}")
        if self.missing_evidence is not None and self.missing_evidence not in FIELD_VALUES["missing_evidence"]:
            raise ValueError(f"invalid missing_evidence {self.missing_evidence!r}")
        if self.required_authority is not None and self.required_authority not in FIELD_VALUES["required_authority"]:
            raise ValueError(f"invalid required_authority {self.required_authority!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GateOutput":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in names})

    def target_json(self, intermediate: bool = True, with_citations: bool = False) -> dict[str, Any]:
        """The JSON object the gate generates, in field order (used for SFT targets and rendering)."""
        out: dict[str, Any] = {}
        for f in output_fields(intermediate):
            out[f] = getattr(self, f)
        if with_citations:
            out["evidence_cited"] = list(self.evidence_cited)
        return out
