"""Resolution loop: ASK_USER and ESCALATE each collect one new piece of evidence and re-run the same gate, at most
`max_rounds` times; anything still unresolved becomes BLOCK. Nothing executes unless the final decision is ALLOW.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from ..data.cases import Case
from ..evidence.context import with_round
from ..gate.schema import FINAL, GateInput, GateOutput


class Gate(Protocol):
    def decide(self, gi: GateInput) -> GateOutput: ...


class Responder(Protocol):
    def respond(self, case: Case, gi: GateInput, out: GateOutput, round_no: int) -> dict: ...


@dataclass
class ResolutionTrace:
    case_id: str
    condition: str
    rounds: list = field(default_factory=list)      # [{"round", "output", "response"?}]
    first_decision: str = "BLOCK"
    final_decision: str = "BLOCK"
    interactions: int = 0
    p_allow: float | None = None                    # first-round p_allow (threshold sweeps, Pareto curves)
    noisy_response: bool = False
    defaulted: bool = False                         # still deferring after max_rounds -> BLOCK

    @property
    def executed(self) -> bool:
        return self.final_decision == "ALLOW"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["executed"] = self.executed
        return d


def resolve(case: Case, gi: GateInput, gate: Gate, user: Responder | None, approver: Responder | None,
            condition: str = "", max_rounds: int = 2, enabled: bool = True) -> ResolutionTrace:
    out = gate.decide(gi)
    tr = ResolutionTrace(case.case_id, condition, first_decision=out.decision, p_allow=out.p_allow)
    tr.rounds.append({"round": 0, "output": out.to_dict()})
    rnd = 0
    while enabled and out.decision not in FINAL and rnd < max_rounds:
        responder = user if out.decision == "ASK_USER" else approver
        if responder is None:
            break
        rnd += 1
        resp = responder.respond(case, gi, out, rnd)
        tr.interactions += 1
        tr.noisy_response |= bool(resp.get("noisy"))
        tr.rounds[-1]["response"] = resp
        asked = {"missing_evidence": out.missing_evidence, "required_authority": out.required_authority}
        gi = with_round(gi, rnd, out.decision, asked, resp)
        out = gate.decide(gi)
        tr.rounds.append({"round": rnd, "output": out.to_dict()})
    if out.decision in FINAL:
        tr.final_decision = out.decision
    else:
        tr.final_decision, tr.defaulted = "BLOCK", True
    return tr
