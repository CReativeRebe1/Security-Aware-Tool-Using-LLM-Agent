"""GateExp: B5 with the agreed deterministic layers around the trained gate (docs/GATE_EVALUATION.md §3).

Pipeline for one gate step:
  augment  -> extra facts computed from the GateInput (intent, risk, data source, split / cumulative payments,
              file labels incl. appended content and unlabelled files); authority is tightened where needed
  pre      -> rules that decide without the model (declined, untrusted provenance, missing authority)
  model    -> the wrapped gate (B5 adapter) on the augmented input
  post     -> rules that can only defer or resolve a repeated question (guards, confirmations, routing)

Every step is recorded in `GateOutput.trace` (the decision log). Rule order is a condition setting
(`gateexp.pre` / `gateexp.post`), so other orders can be replayed from the log without a GPU.
A CONFIRM is an ASK_USER whose `guard` starts with "confirm:"; the report counts it apart from other deferrals.
"""

from __future__ import annotations

import dataclasses
import re
from functools import lru_cache
from typing import Sequence

import yaml

from ..config import load_config
from ..evidence.checks import _ACTION_WORDS, numbers
from ..evidence.sensitivity import CLEARANCE, max_label, rank
from ..evidence.tools_registry import spec
from .guards import _approved, _confirmed, _payee_limit, _transfer_rules, apply_guards, over_cumulative
from .schema import GateInput, GateOutput

PRE = ("declined", "untrusted_provenance", "authority")
POST = ("guards", "no_reask", "intent_confirm", "new_payee_confirm", "unlabelled_external", "route_authority")
HIGH_RISK = {"disclose", "delete", "transfer", "account_change"}
_PAYMENTS = ("send_money", "schedule_transaction")

# --- facts ---------------------------------------------------------------------------------------------------------
_DELEGATION = re.compile(
    r"\b(do|follow|perform|complete|carry out|execute|handle|act on|deal with)\b.{0,60}?"
    r"\b(says?|said|asks?|asked|wants?|wrote|requests?|requested|instructions?|steps?|e-?mail|message|letter|note)\b",
    re.IGNORECASE)
_NOT_REQUEST = re.compile(r"\btell me\b|\bshow me\b", re.IGNORECASE)


def intent(gi: GateInput) -> str:
    """asked | delegated | not_asked: did the user's own words ask for this kind of action?
    Stricter than checks.action_requested: whole words only ("payment" is not "pay"), and open delegation to
    content ("do what the email says") is its own value."""
    prompt = str(gi.user.get("prompt") or "")
    if _DELEGATION.search(prompt):
        return "delegated"
    words = _ACTION_WORDS.get(spec(gi.proposed_call["function"]).action)
    if words is None:
        return "asked"
    text = _NOT_REQUEST.sub(" ", prompt)
    return "asked" if re.search(rf"\b(?:{words})\b", text, re.IGNORECASE) else "not_asked"


def risk(gi: GateInput) -> str:
    """high: hard to undo, or money / data leaves. low actions become high for an unknown recipient or another
    person's resource."""
    action = spec(gi.proposed_call["function"]).action
    if action in HIGH_RISK:
        return "high"
    if not gi.proposed_call.get("state_changing"):
        return "low"
    auth = gi.authority or {}
    parties = [str(p) for p in auth.get("affected_party", [])]
    if any(p.startswith(("unknown:", "new_payee:")) for p in parties):
        return "high"
    if auth.get("resource_owner") not in (None, "current_user"):
        return "high"
    return "low"


def data_source(gi: GateInput) -> str:
    """user | third_party | untrusted: where the authority-bearing arguments came from (C8 'is the data genuine')."""
    if gi.provenance is None:
        return "unknown"
    content = set(spec(gi.proposed_call["function"]).content_args)
    trust = [r.get("trust") for r in gi.provenance if r.get("kind") == "arg" and r.get("arg") not in content]
    call = next((r for r in gi.provenance if r.get("kind") == "call"), {})
    if call.get("trust") == "untrusted" or "untrusted" in trust:
        return "untrusted"
    if "third_party" in trust:
        return "third_party"
    return "user"


# --- requested total and split payments (C10) ----------------------------------------------------------------------
_MONEY = re.compile(r"(?:(?:€|\$|£|\b(?:eur|usd|gbp|chf)\b)\s*)?(?<![\w.,#-])(\d[\d,]*(?:\.\d+)?)(\s*k\b)?",
                    re.IGNORECASE)
_NOT_AMOUNT = re.compile(r"(invoice|bill|order|ref(?:erence)?|no\.?|number|id|account|#)\s*$", re.IGNORECASE)
_DOC_TOTAL = re.compile(r"(?:total|amount due|amount|balance due|sum)\D{0,20}?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_POINTS_AT_DOC = re.compile(r"\b(bill|invoice|statement|document|file|letter)\b", re.IGNORECASE)


def requested_amounts(gi: GateInput) -> list[float]:
    """Amounts the user asked to pay: numbers in the prompt that are not ids / invoice numbers ("1.8k" = 1800),
    plus the total of a bill when the prompt points at one."""
    prompt = str(gi.user.get("prompt") or "")
    out = []
    for m in _MONEY.finditer(prompt):
        if _NOT_AMOUNT.search(prompt[:m.start()]):
            continue
        try:
            x = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append(x * 1000 if m.group(2) else x)
    if _POINTS_AT_DOC.search(prompt):
        for t in gi.untrusted_content:
            for m in _DOC_TOTAL.finditer(t.get("text", "")):
                out.append(float(m.group(1).replace(",", "")))
    return out


def split_payment(gi: GateInput) -> bool:
    """The call pays part of a larger requested payment whose total is over the payee limit (BANK-2.4), or the
    running total passes a limit. Judged at the first part, so nothing is paid before approval."""
    call = gi.proposed_call
    if call["function"] not in _PAYMENTS:
        return False
    try:
        amount = float((call.get("args") or {}).get("amount"))
    except (TypeError, ValueError):
        return False
    limit = _payee_limit(gi, _transfer_rules(gi.suite))
    if any(x > amount and x > limit for x in requested_amounts(gi)):
        return True
    return over_cumulative(gi)


# --- labels (C11 / C12) --------------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _labels(suite: str) -> dict:
    path = load_config().resources_dir / "sensitivity" / f"{suite}.yaml"
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _content_label(suite: str, text: str) -> str | None:
    low = text.lower()
    hits = [m["label"] for m in _labels(suite).get("markers", []) if m["text"].lower() in low]
    return max_label(hits) if hits else None


_ID_IN_TEXT = re.compile(r"id_:\s*'?(\d+)'?")
_CONTENT_IN_TEXT = re.compile(r"content:\s*'?(.*?)'?\s*\n\s*filename:", re.DOTALL)
_READS = ("get_file_by_id", "read_file")


def file_labels(gi: GateInput) -> dict[str, tuple[str, str]]:
    """file id -> (label, source) for the files this call sends. source: config | content | default.
    A file's label is the highest label ever written into it (create + append), and at least the suite default
    when the config does not list it. Writes after reading a labelled file inherit its label (taint)."""
    if gi.suite != "workspace":
        return {}
    call, args = gi.proposed_call, gi.proposed_call.get("args") or {}
    ids = []
    if args.get("file_id") is not None:
        ids.append(str(args["file_id"]))
    for a in args.get("attachments") or []:
        if isinstance(a, dict) and a.get("file_id") is not None:
            ids.append(str(a["file_id"]))
    if not ids or call["function"] not in ("send_email", "share_file"):
        return {}
    cfg = _labels(gi.suite)
    configured = {str(k): v for k, v in (cfg.get("files") or {}).items()}
    default = cfg.get("default_label", "INTERNAL")
    written: dict[str, list[str]] = {}
    for t in gi.untrusted_content:                       # files created in this run show up as tool output
        if "create_file" in t.get("source", ""):
            m, c = _ID_IN_TEXT.search(t.get("text", "")), _CONTENT_IN_TEXT.search(t.get("text", ""))
            if m:
                written.setdefault(m.group(1), []).append(c.group(1) if c else t.get("text", ""))
    taint: list[str] = []
    for p in gi.prior_calls:
        a = p.get("args") or {}
        if p.get("function") in _READS and str(a.get("file_id")) in configured:
            taint.append(configured[str(a["file_id"])])
        if p.get("function") == "append_to_file" and a.get("file_id") is not None:
            written.setdefault(str(a["file_id"]), []).append(str(a.get("content") or ""))
    out = {}
    for fid in ids:
        labels, source = [], "default"
        if fid in configured:
            labels.append(configured[fid]); source = "config"
        for text in written.get(fid, []):
            lab = _content_label(gi.suite, text)
            if lab:
                labels.append(lab); source = "content" if source == "default" else source
        if fid in written and taint:
            labels.append(max_label(taint))
        if source == "default":
            labels.append(default)
        out[fid] = (max_label(labels), source)
    return out


_CAPS = {"self": "RESTRICTED", "internal": "CONFIDENTIAL", "client": "INTERNAL"}


def _disclose_role(label: str, classes: list[str], owned_by_other: bool) -> tuple[str, str] | None:
    """(required role, basis) for sending `label` data to these destination classes (workspace user_rules)."""
    worst = None
    for cls in classes:
        if rank(label) <= rank(_CAPS.get(cls, "PUBLIC")):
            continue
        if label == "RESTRICTED":
            return "security_admin", "disclose_restricted"
        if label == "CONFIDENTIAL" and cls != "internal":
            worst = ("resource_owner", "disclose_confidential_external") if owned_by_other else \
                ("manager", "disclose_confidential_external")
        else:
            worst = worst or ("manager", "disclose_internal_unknown_external")
    return worst


_ROLE_ORDER = ("none", "current_user", "resource_owner", "manager", "security_admin")


def augment(gi: GateInput) -> tuple[GateInput, dict]:
    """Copy of the input with the C8 / C10 / C11 / C12 facts added, and the facts as a dict for the log."""
    out = gi.copy()
    facts = {"intent": intent(gi), "risk": risk(gi), "data_source": data_source(gi)}
    auth = dict(out.authority or {}) if out.authority is not None else None
    if auth is not None and spec(gi.proposed_call["function"]).action == "transfer" and split_payment(gi):
        facts["split_payment"] = True
        auth["user_may_authorize"] = False
        if _ROLE_ORDER.index(auth.get("required_role", "current_user")) < _ROLE_ORDER.index("manager"):
            auth["required_role"] = "manager"
        auth["basis"] = [*auth.get("basis", []), "transfer_over_limit"]
    labels = file_labels(gi)
    if labels:
        facts["file_labels"] = {k: list(v) for k, v in labels.items()}
        label = max_label([v[0] for v in labels.values()])
        if any(v[1] == "default" for v in labels.values()):
            facts["label_source"] = "default"
        sens = dict(out.sensitivity or {}) if out.sensitivity is not None else None
        if sens is not None:
            sens["resource"] = max_label([sens.get("resource") or "PUBLIC", label])
            dest = sens.get("destination")
            if dest and rank(sens["resource"]) > rank(dest):
                sens["flow"] = "high_to_low"
            out.sensitivity = sens
        if auth is not None:
            classes = [str(p).split(":")[0] for p in auth.get("affected_party", [])]
            need = _disclose_role(label, classes, auth.get("resource_owner") not in (None, "current_user"))
            if need and _ROLE_ORDER.index(need[0]) > _ROLE_ORDER.index(auth.get("required_role", "current_user")):
                auth["required_role"], auth["user_may_authorize"] = need[0], False
                auth["basis"] = [*auth.get("basis", []), need[1]]
                facts["label_escalation"] = need[1]
    if auth is not None:
        out.authority = auth
    out.checks = {**(out.checks or {}), "user_intent": facts["intent"], "risk": facts["risk"],
                  "data_source": facts["data_source"]}
    if facts.get("split_payment"):
        out.checks["split_payment"] = "part_of_larger_payment"
    if facts.get("label_source"):
        out.checks["data_label"] = "unlabelled (default INTERNAL)"
    return out, facts


# --- rules ---------------------------------------------------------------------------------------------------------
def _declined(gi: GateInput) -> bool:
    return any((h["kind"] == "ASK_USER" and h.get("confirmed") is False) or
               (h["kind"] == "ESCALATE" and h.get("approved") is False) for h in gi.resolution_history)


def _external(gi: GateInput) -> bool:
    return any(not str(p).startswith(("internal:", "self:")) for p in (gi.authority or {}).get("affected_party", []))


def pre_rule(name: str, gi: GateInput, facts: dict) -> GateOutput | None:
    auth = gi.authority or {}
    if name == "declined" and _declined(gi):
        return GateOutput("BLOCK", "user_intent", "current_user", guard="pre:declined")
    if name == "untrusted_provenance" and facts["data_source"] == "untrusted" and not _confirmed(gi):
        return GateOutput("BLOCK", "none", "none", guard="pre:untrusted_provenance")
    if name == "authority" and auth and auth.get("user_may_authorize") is False and not _approved(gi):
        if facts.get("label_escalation") and facts.get("label_source") == "default" and not _confirmed(gi):
            # the label is only the default: ask the owner what the data is before involving an approver
            return GateOutput("ASK_USER", "data_classification", "current_user", guard="confirm:data_label")
        role = auth.get("required_role") if auth.get("required_role") not in (None, "none", "current_user") \
            else "manager"
        return GateOutput("ESCALATE", "approval", role, guard="pre:authority")
    return None


def _ask(out: GateOutput, missing: str, reason: str) -> GateOutput:
    return dataclasses.replace(out, decision="ASK_USER", missing_evidence=missing, required_authority="current_user",
                               guard=reason)


def post_rule(name: str, gi: GateInput, facts: dict, out: GateOutput, space: Sequence[str]) -> GateOutput:
    auth = gi.authority or {}
    settled = _confirmed(gi) or _approved(gi)
    if name == "guards":
        return apply_guards(gi, out, space)
    if name == "no_reask" and out.decision == "ASK_USER" and _confirmed(gi) and auth.get("user_may_authorize", True):
        return dataclasses.replace(out, decision="ALLOW", missing_evidence="none", guard="post:no_reask")
    if out.decision != "ALLOW" or settled:
        if name == "route_authority" and out.decision == "ASK_USER" and auth.get("user_may_authorize") is False \
                and not _approved(gi):
            role = auth.get("required_role") if auth.get("required_role") not in (None, "none", "current_user") \
                else "manager"
            return dataclasses.replace(out, decision="ESCALATE", missing_evidence="approval",
                                       required_authority=role, guard="post:route_authority")
        return out
    if name == "intent_confirm" and facts["risk"] == "high" and facts["intent"] in ("not_asked", "delegated"):
        return _ask(out, "user_intent", f"confirm:intent_{facts['intent']}")
    if name == "new_payee_confirm" and spec(gi.proposed_call["function"]).action == "transfer" and \
            any(str(p).startswith("new_payee:") for p in auth.get("affected_party", [])):
        return _ask(out, "recipient_identity", "confirm:new_payee")
    if name == "unlabelled_external" and facts.get("label_source") == "default" and _external(gi):
        return _ask(out, "data_classification", "confirm:data_label")
    return out


class ExpGate:
    """Wraps the B5 gate. The wrapped gate's cache keys on the augmented prompt, so runs stay resumable."""

    def __init__(self, gate, decision_space: Sequence[str], pre: Sequence[str] = PRE, post: Sequence[str] = POST,
                 show_facts: bool = True):
        self.gate, self.space = gate, tuple(decision_space)
        self.pre, self.post, self.show_facts = tuple(pre), tuple(post), show_facts

    def decide(self, gi: GateInput) -> GateOutput:
        aug, facts = augment(gi)
        steps = []
        for name in self.pre:
            hit = pre_rule(name, aug, facts)
            steps.append({"rule": name, "fired": hit is not None})
            if hit is not None:
                return dataclasses.replace(hit, trace={"facts": facts, "steps": steps, "model": None})
        model_in = aug if self.show_facts else dataclasses.replace(aug, checks=gi.checks)
        out = self.gate.decide(model_in)
        model = {"decision": out.decision, "missing_evidence": out.missing_evidence,
                 "required_authority": out.required_authority, "p_allow": out.p_allow}
        for name in self.post:
            before = out.decision
            out = post_rule(name, aug, facts, out, self.space)
            steps.append({"rule": name, "fired": out.decision != before, "decision": out.decision})
        return dataclasses.replace(out, trace={"facts": facts, "steps": steps, "model": model})
