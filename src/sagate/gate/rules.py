"""B1: deterministic rules over the same GateInput the learned gates see (proposal §7, ARCHITECTURE.md §5.5).

Ordered rules; the first that fires decides. Any evidence field removed by EvidenceMask is simply skipped.
Four-way output; the binary projection (ASK/ESCALATE -> BLOCK) is scored by the evaluator.
"""

from __future__ import annotations

from typing import Sequence

from ..config import FOUR_WAY
from ..evidence.tools_registry import spec
from .schema import GateInput, GateOutput, collapse_decision


def _out(decision: str, missing: str = "none", authority: str = "none", cited: list | None = None) -> GateOutput:
    return GateOutput(decision=decision, missing_evidence=missing, required_authority=authority,
                      evidence_cited=cited or [])


def _arg_records(gi: GateInput, args: Sequence[str]) -> list[dict]:
    return [r for r in gi.provenance or [] if r.get("kind") == "arg" and r.get("arg") in args]


def _clause_ids(gi: GateInput, *prefixes: str) -> list[str]:
    return [c["id"] for c in gi.policy_clauses or [] if any(c["id"].endswith(p) for p in prefixes)]


class RulesGate:
    name = "b1_rules"

    def __init__(self, decision_space: Sequence[str] = FOUR_WAY):
        self.space = tuple(decision_space)

    def decide(self, gi: GateInput) -> GateOutput:
        out = self._decide(gi)
        out.decision = collapse_decision(out.decision, self.space)
        out.p_allow = 1.0 if out.decision == "ALLOW" else 0.0
        return out

    def _decide(self, gi: GateInput) -> GateOutput:
        call = gi.proposed_call
        if not call.get("state_changing"):
            return _out("ALLOW")
        sp = spec(call["function"])
        hist = gi.resolution_history
        approved = [h for h in hist if h["kind"] == "ESCALATE" and h.get("approved")]
        denied = [h for h in hist if h["kind"] == "ESCALATE" and not h.get("approved")]
        confirmed = [h for h in hist if h["kind"] == "ASK_USER" and h.get("confirmed")]
        declined = [h for h in hist if h["kind"] == "ASK_USER" and h.get("confirmed") is False]
        auth = gi.authority
        role = (auth or {}).get("required_role", "current_user")

        # R1 — the call was caused by, or copies values from, untrusted (injected) content
        if gi.provenance is not None:
            call_rec = next((r for r in gi.provenance if r.get("kind") == "call"), None)
            bad_args = [r for r in gi.provenance if r.get("kind") == "arg" and r.get("trust") == "untrusted"]
            if (call_rec and call_rec.get("trust") == "untrusted") or bad_args:
                ids = ([call_rec["id"]] if call_rec else []) + [r["id"] for r in bad_args]
                return _out("BLOCK", cited=ids + _clause_ids(gi, "-5.1"))

        # R2 — the user declined, or the approver denied, in an earlier round
        if declined:
            return _out("BLOCK", "user_intent", "current_user")
        if denied:
            return _out("BLOCK", "approval", role if role not in ("none", "current_user") else "manager")

        # R3 — restricted data leaving to a lower-cleared destination is never released
        sens = gi.sensitivity
        if sens is not None and sens.get("flow") == "high_to_low" and sens.get("resource") == "RESTRICTED":
            return _out("BLOCK", "none", "security_admin", cited=_clause_ids(gi, "-2.5", "-4.1"))

        # R4 — the action needs authority the user does not hold
        if auth is not None:
            if not auth.get("user_may_authorize", True) and not approved:
                return _out("ESCALATE", "approval", role)
        elif sens is not None and sens.get("flow") == "high_to_low" and not approved:
            return _out("ESCALATE", "data_classification", "manager")

        # R5 — user-resolvable gaps: who receives it / which resource, when not given by the user
        if not confirmed and gi.provenance is not None:
            if sp.destination_args and self._needs_recipient_check(gi, sp.destination_args):
                return _out("ASK_USER", "recipient_identity", "current_user")
            if sp.action == "delete" and sp.resource_arg:
                recs = _arg_records(gi, [sp.resource_arg])
                if recs and all(r.get("trust") != "trusted" for r in recs):
                    return _out("ASK_USER", "resource_target", "current_user")

        return _out("ALLOW", "none", "current_user")

    @staticmethod
    def _needs_recipient_check(gi: GateInput, dest_args: Sequence[str]) -> bool:
        """A destination not named by the user and not internal / approved."""
        recs = _arg_records(gi, dest_args)
        if not recs or all(r.get("trust") == "trusted" for r in recs):
            return False
        if gi.authority is None:
            return True
        risky = ("unknown:", "new_payee:")
        return any(p.startswith(risky) for p in gi.authority.get("affected_party", []))
