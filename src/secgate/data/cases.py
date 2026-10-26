"""Case = GateInput + where it came from + (once annotated) gold labels and the fixed user response."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from ..gate.schema import GateInput
from .io import read_jsonl, write_jsonl

GOLD_FIELDS = ("gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority",
               "gold_clause_ids")


@dataclass
class Case:
    input: GateInput                     # full evidence, oracle provenance
    pool: str                            # train | dev | test
    subset: str = "executable"           # executable | decision_only
    scenario_id: str | None = None
    proposal_id: str | None = None
    category: str | None = None          # benign | injection_goal | injection_scenario | authority_spoofing | ...
    author: str | None = None            # decision-only cases: who wrote it
    alt_provenance: dict = field(default_factory=dict)   # {"inferred": {...}}
    meta: dict = field(default_factory=dict)             # trace id, pipelines, heuristic flags (analysis only)
    gold_decision: str | None = None
    gold_final_action: str | None = None
    gold_missing_evidence: str | None = None
    gold_required_authority: str | None = None
    gold_clause_ids: list | None = None
    # fixed reply for ASK_USER: {"clean": {text, confirmed, provides}, "noisy": {...} | None}
    user_response: dict | None = None
    annotations: list = field(default_factory=list)

    @property
    def case_id(self) -> str:
        return self.input.case_id

    @property
    def has_gold(self) -> bool:
        return self.gold_decision is not None and self.gold_final_action is not None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["input"] = self.input.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Case":
        d = dict(d)
        d["input"] = GateInput.from_dict(d["input"])
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in names})


def iter_cases(path: str | Path) -> Iterator[Case]:
    for row in read_jsonl(path):
        yield Case.from_dict(row)


def load_cases(path: str | Path) -> list[Case]:
    return list(iter_cases(path))


def save_cases(path: str | Path, cases: Iterable[Case]) -> int:
    return write_jsonl(path, (c.to_dict() for c in cases))
