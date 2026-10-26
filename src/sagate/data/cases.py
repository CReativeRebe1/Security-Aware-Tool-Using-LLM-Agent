"""TestCase / TrainCase: a GateInput plus metadata and gold fields (ARCHITECTURE.md §4.3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from ..gate.schema import GateInput
from .loaders import read_jsonl, write_jsonl

GOLD_FIELDS = (
    "gold_decision",
    "gold_final_action",
    "gold_missing_evidence",
    "gold_required_authority",
    "gold_clause_ids",
)


@dataclass
class Case:
    input: GateInput                        # full evidence, oracle provenance
    pool: str                               # train | dev | test
    subset: str = "executable"              # executable | decision_only
    scenario_id: str | None = None
    proposal_id: str | None = None
    category: str | None = None             # e.g. injection, benign, authority_spoofing
    alt_provenance: dict = field(default_factory=dict)   # {"inferred": [...records...]}
    meta: dict = field(default_factory=dict)             # trace_id, pipeline, heuristic flags (analysis only)
    # gold (human, adjudicated) — None until annotated
    gold_decision: str | None = None
    gold_final_action: str | None = None
    gold_missing_evidence: str | None = None
    gold_required_authority: str | None = None
    gold_clause_ids: list | None = None
    user_response: dict | None = None       # {text, provides, noisy, noisy_text, noisy_provides}
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


def load_cases(path: str | Path) -> list[Case]:
    return [Case.from_dict(r) for r in read_jsonl(path)]


def iter_cases(path: str | Path) -> Iterator[Case]:
    for r in read_jsonl(path):
        yield Case.from_dict(r)


def save_cases(path: str | Path, cases: Iterable[Case]) -> int:
    return write_jsonl(path, (c.to_dict() for c in cases))


def attach_gold(cases: list[Case], gold_rows: Iterable[dict]) -> int:
    """Copy gold fields (from adjudicated annotation rows keyed by case_id) onto cases. Returns #matched."""
    by_id = {r["case_id"]: r for r in gold_rows}
    n = 0
    for c in cases:
        g = by_id.get(c.case_id)
        if not g:
            continue
        for f in GOLD_FIELDS:
            if g.get(f) not in (None, ""):
                setattr(c, f, g[f])
        if g.get("user_response"):
            c.user_response = g["user_response"]
        n += 1
    return n
