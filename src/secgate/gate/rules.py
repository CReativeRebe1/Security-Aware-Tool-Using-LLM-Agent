"""B1: deterministic rules written from the two handbooks, over the same GateInput the learned gates see.

Rules are checked in order and the first that fires decides. Evidence removed by an ablation is simply not used
(the rule falls back to what is still visible). Four-way output; the evaluator also scores its binary projection.
Rules only read observable evidence; they do not know what was injected or what the user really intended.
"""

from __future__ import annotations

import re
from typing import Sequence

from ..config import FOUR_WAY
from .schema import GateInput, GateOutput, restrict

_FREEMAIL = ("gmail.com", "yahoo.com", "hotmail.com", "aol.com", "outlook.com")
_BRAND = re.compile(r"facebook|google|apple|paypal|microsoft|netflix|bank|tech-?services")


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def looks_alike(address: str, org_domains: Sequence[str] = ("bluesparrowtech.com",)) -> bool:
    """WS-2.6: a domain one or two edits away from the company's (or one edit from a common mail provider), or a
    well-known service imitated from a free-mail account."""
    a = address.strip().lower()
    if "@" not in a:
        return False
    local, domain = a.rsplit("@", 1)
    if any(0 < edit_distance(domain, d) <= 2 for d in org_domains):
        return True
    if any(edit_distance(domain, d) == 1 for d in _FREEMAIL):
        return True
    return domain in _FREEMAIL and bool(_BRAND.search(local))


def _out(decision: str, missing: str = "none", authority: str = "none", cited=None) -> GateOutput:
    return GateOutput(decision=decision, missing_evidence=missing, required_authority=authority,
                      evidence_cited=list(cited or []))


class RulesGate:
    name = "b1_rules"

    def __init__(self, decision_space: Sequence[str] = FOUR_WAY):
        self.space = tuple(decision_space)

    def decide(self, gi: GateInput) -> GateOutput:
        out = self._decide(gi)
        out.decision = restrict(out.decision, self.space)
        out.p_allow = 1.0 if out.decision == "ALLOW" else 0.0
        return out

    # --- helpers --------------------------------------------------------------------------------------------
    @staticmethod
    def _arg_trust(gi: GateInput, arg: str) -> str | None:
        """Trust of an argument; without provenance evidence, 'user' iff the value is in the request text."""
        if gi.provenance is not None:
            recs = [r for r in gi.provenance.get("args", []) if r["arg"] == arg]
            return recs[0]["trust"] if recs else None
        v = gi.action.get("args", {}).get(arg)
        if v in (None, "", []):
            return None
        vals = v if isinstance(v, list) else [v]
        prompt = (gi.request.get("prompt") or "").lower()
        return "user" if all(str(x).lower() in prompt for x in vals) else "unknown"

    @staticmethod
    def _clauses(gi: GateInput, *suffixes: str) -> list[str]:
        return [c["id"] for c in gi.policy or [] if any(c["id"].endswith(s) for s in suffixes)]

    # --- the rules ------------------------------------------------------------------------------------------
    def _decide(self, gi: GateInput) -> GateOutput:
        a = gi.action
        if not a.get("state_changing"):
            return _out("ALLOW")
        args = a.get("args") or {}
        hist = gi.resolution
        declined = any(r["kind"] == "ASK_USER" and r.get("confirmed") is False for r in hist)
        confirmed = any(r["kind"] == "ASK_USER" and r.get("confirmed") is True for r in hist)
        denied = any(r["kind"] == "ESCALATE" and r.get("approved") is False for r in hist)
        approved = any(r["kind"] == "ESCALATE" and r.get("approved") is True for r in hist) or \
            bool((gi.authority or {}).get("approvals"))
        auth = gi.authority
        role = (auth or {}).get("required_authority", "current_user")

        # R1 — WS-6.3 / BANK-6.3: a "no" from the user or a denial from an approver ends the matter
        if declined:
            return _out("BLOCK", "user_intent", "current_user")
        if denied:
            return _out("BLOCK", "approval", role if role not in ("none", "current_user") else "manager")

        # R2 — WS-5.1/5.2, BANK-5.1: caused by, or copies values from, instructions inside content
        if gi.provenance is not None:
            o = gi.provenance["origin"]
            bad = [r["id"] for r in gi.provenance.get("args", []) if r["trust"] == "untrusted"]
            if o["trust"] == "untrusted" or bad:
                return _out("BLOCK", cited=[o["id"], *bad, *self._clauses(gi, "-5.1", "-5.2")])

        # R3 — prohibited regardless of approval (RESTRICTED outside the company, over the manager maximum)
        sens = gi.sensitivity
        if auth is not None and auth.get("prohibited"):
            return _out("BLOCK", cited=self._clauses(gi, "-2.5", "-2.4"))
        if auth is None and sens is not None and sens.get("data_label") == "RESTRICTED" \
                and sens.get("flow") == "high_to_low":
            return _out("BLOCK", cited=self._clauses(gi, "-2.5"))

        # R4 — gaps the user can close (asked before any escalation)
        if not confirmed:
            ask = self._user_gap(gi, args)
            if ask:
                return _out("ASK_USER", ask, "current_user", cited=self._clauses(gi, "-6.1"))

        # R5 — authority the user does not hold
        if not approved:
            if auth is not None and not auth.get("user_may_authorize", True):
                return _out("ESCALATE", "approval", role, cited=self._clauses(gi, "-6.2"))
            if auth is None and sens is not None and sens.get("flow") == "high_to_low":
                return _out("ESCALATE", "data_classification", "manager")

        return _out("ALLOW", "none", "current_user")

    def _user_gap(self, gi: GateInput, args: dict) -> str | None:
        a, auth = gi.action, gi.authority
        fn, cls = a["function"], a.get("action_class")
        recipients = (auth or {}).get("recipients")
        if recipients is None:      # no authority evidence: read destinations straight from the arguments
            recipients = []
            for k in ("recipients", "cc", "bcc", "email", "participants", "recipient"):
                v = args.get(k)
                recipients += [{"value": str(x), "relation": None} for x in (v if isinstance(v, list) else [v]) if x]
        dest_arg = {"send_email": "recipients", "share_file": "email", "create_calendar_event": "participants",
                    "add_calendar_event_participants": "participants", "send_money": "recipient",
                    "schedule_transaction": "recipient", "update_scheduled_transaction": "recipient"}.get(fn)
        dest_trust = self._arg_trust(gi, dest_arg) if dest_arg else None

        # WS-2.6: look-alike or imitation addresses always need the user's confirmation
        if gi.suite == "workspace" and any(looks_alike(r["value"]) for r in recipients):
            return "recipient_identity"
        # WS-2.3: internal data to an unknown address needs the exact address confirmed
        if auth is not None and "internal_data_to_unknown_recipient" in auth.get("basis", []):
            return "recipient_identity"
        # WS-2.7 / WS-4.2: unknown recipient (or invitee) that the user did not name
        if gi.suite == "workspace" and dest_trust not in (None, "user"):
            if any(r.get("relation") in ("unknown", None) for r in recipients):
                return "recipient_identity"
        # BANK-2.3: a new payee whose IBAN did not come from the account holder
        if gi.suite == "banking" and dest_trust not in (None, "user"):
            if any(r.get("relation") in ("new_payee", None) for r in recipients):
                return "recipient_identity"
        # WS-3.4: deletion target inferred from content
        if cls == "delete" and fn in ("delete_file", "cancel_calendar_event"):
            res_arg = "file_id" if fn == "delete_file" else "event_id"
            if self._arg_trust(gi, res_arg) not in (None, "user"):
                return "resource_target"
        return None
