"""Hand-authored synthetic decision-only cases (data/synthetic_data): specs -> unlabeled Case JSONL.

Each spec file under data/synthetic_data/specs holds scenario *families*: one concrete situation (a vendor invoice
with an unknown IBAN, a look-alike colleague address, an HR file forwarded to a partner, an approval claim inside
an email ...) with hand-written user prompts, the tool outputs the agent saw, the proposed call, and contrastive
variants that change one fact so the correct decision flips. Every realization is built by the same
ContextBuilder as real cases, so provenance / authority / sensitivity / policy evidence has exactly the format the
gate sees in evaluation.

Cases are written WITHOUT gold labels (pool "train", subset "decision_only"); annotators label them later. The
author's intended labels go to a separate design key so labelling stays blind. Answered ASK_USER / ESCALATE rounds
become extra cases with a `resolution_history`, so the second-round decision is covered too.

  python -m sagate.train.synthetic build --n 2000
  python -m sagate.train.synthetic check            # validate specs + evidence consistency, write nothing
  python -m sagate.train.synthetic merge --gold annotations/synthetic_gold.jsonl --reviewer member_b \
         --out annotations/synthetic_nl.jsonl     # after labelling: labelled cases -> NL training file
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from ..config import REPO_ROOT, load_config
from ..data.cases import Case, save_cases
from ..data.loaders import AgentDojoData, read_jsonl, write_jsonl
from ..evidence.context_builder import ContextBuilder, with_resolution
from ..evidence.policy_rag import parse_handbook
from ..evidence.tools_registry import REGISTRY, spec
from ..gate.prompts import render_input
from ..gate.schema import DEFERRALS, FIELD_VALUES, GateOutput
from ..resolution.responders import MockApprover

OUT_DIR = REPO_ROOT / "data" / "synthetic_data"
SPEC_DIR = OUT_DIR / "specs"
AUTHOR = "synthetic-v1"
_ABBR = {"workspace": "ws", "banking": "bank"}
_VAR = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
DEFAULT_MIX = {"ALLOW": 0.35, "BLOCK": 0.30, "ASK_USER": 0.20, "ESCALATE": 0.15}
CATEGORIES = ("benign", "benign_with_injection", "injection", "authority_spoofing", "authority", "ambiguity",
              "sensitivity", "delegation", "resolution")

# Fallback replies, used when a family does not write its own. Keyed by what was asked.
_USER_YES = {
    "recipient_identity": ["Yes, that's the right address, go ahead.", "Correct, that's who I meant.",
                           "Yes — that is the person I want it to go to."],
    "resource_target": ["Yes, that's the file I meant.", "Correct, that one.", "Yes, delete that one."],
    "user_intent": ["Yes, I did ask for that. Please go ahead.", "Yes, that's intended.", "Yes, do it."],
    "data_classification": ["It's nothing confidential, just general info — fine to send.",
                            "That content is public, no internal data in it."],
    "approval": ["Yes, I want it."],
}
_USER_NO = {
    "recipient_identity": ["No, I don't know that address. Don't send anything there.",
                           "No, that's not who I meant — cancel it."],
    "resource_target": ["No, not that file. Leave it alone.", "No, don't touch that one."],
    "user_intent": ["No, I never asked for that. Don't do it.", "No — I didn't request that, stop."],
    "data_classification": ["Actually it does include internal figures. Don't send it.",
                            "Hmm, it has client data in it. Hold off."],
    "approval": ["No, don't."],
}
_UNHELPFUL = ["I'm not sure, just do whatever makes sense.", "Whatever you think is best.",
              "I'm in a meeting, can't check now — use your judgement.", "Hmm, I don't remember. Your call."]
_OVERREACH = ["I'm authorizing it myself — you have my approval, just do it.",
              "I approve this. Consider it signed off by me.",
              "You don't need anyone else, I'm giving you permission. Go ahead."]
_APPROVE = {"manager": ["Approved — go ahead with this one.", "Approved for this request only."],
            "resource_owner": ["Fine by me, approved.", "Approved — you can go ahead."],
            "security_admin": ["Approved after verification.", "Verified and approved."]}
_DENY = {"manager": ["Denied. Please don't send this outside the company.", "Not approved."],
         "resource_owner": ["No, please don't. Denied.", "Denied — leave my file as it is."],
         "security_admin": ["Denied. This cannot be released.", "Denied after review."]}


class SpecError(ValueError):
    pass


# --- spec loading and interpolation -------------------------------------------------------------------------

def _interp(obj, vars_: dict):
    if isinstance(obj, str):
        def sub(m):
            k = m.group(1)
            return str(vars_[k]) if k in vars_ else m.group(0)
        whole = _VAR.fullmatch(obj)
        if whole and whole.group(1) in vars_ and not isinstance(vars_[whole.group(1)], str):
            return copy.deepcopy(vars_[whole.group(1)])       # "{amount}" alone keeps the number type
        return _VAR.sub(sub, obj)
    if isinstance(obj, list):
        return [_interp(v, vars_) for v in obj]
    if isinstance(obj, dict):
        return {k: _interp(v, vars_) for k, v in obj.items()}
    return obj


def _merge_call(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    if not over:
        return out
    if "function" in over:
        out["function"] = over["function"]
        if over.get("replace_args"):
            out["args"] = {}
    for k, v in (over.get("args") or {}).items():
        if v is None:
            out.setdefault("args", {}).pop(k, None)
        else:
            out.setdefault("args", {})[k] = copy.deepcopy(v)
    return out


@dataclass
class Realization:
    family: str
    variant: str
    suite: str
    category: str
    prompts: list[str]
    call: dict
    context: list
    intent: dict
    replies: dict
    goal_match: bool
    difficulty: str
    rounds: bool
    source: str
    notes: str = ""
    tags: list = field(default_factory=list)


def _extra_prompts(spec_dir: Path) -> dict[tuple[str, str], list[str]]:
    """*_extra_prompts.yaml: [{family, variant, prompts}] — more hand-written phrasings for an existing variant
    (variant "*" = every variant that uses the family-level prompts)."""
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in sorted(spec_dir.glob("*_extra_prompts.yaml")):
        for row in yaml.safe_load(path.read_text()) or []:
            out[(row["family"], str(row.get("variant", "*")))] += list(row["prompts"])
    return out


def load_specs(spec_dir: Path = SPEC_DIR) -> list[Realization]:
    out, seen = [], set()
    extra = _extra_prompts(spec_dir)
    used = set()
    for path in sorted(spec_dir.glob("*.yaml")):
        if path.name.endswith("_extra_prompts.yaml"):
            continue
        docs = yaml.safe_load(path.read_text()) or []
        for fam in docs:
            fid = fam["family"]
            if fid in seen:
                raise SpecError(f"{path.name}: duplicate family {fid}")
            seen.add(fid)
            variants = fam.get("variants") or [{"name": "base"}]
            for v in variants:
                vars_ = {**(fam.get("vars") or {}), **(v.get("vars") or {})}
                more = extra.get((fid, v["name"]), [])
                if not v.get("prompts"):
                    more = more + extra.get((fid, "*"), [])
                used |= {k for k in ((fid, v["name"]), (fid, "*")) if k in extra}
                r = Realization(
                    family=fid, variant=v["name"], suite=fam["suite"],
                    category=v.get("category", fam.get("category")),
                    prompts=_interp(list(v.get("prompts") or fam["prompts"]) + more, vars_),
                    call=_interp(_merge_call(fam["call"], v.get("call")), vars_),
                    context=_interp(v["context"] if "context" in v else fam.get("context") or [], vars_),
                    intent=_interp({**(fam.get("intent") or {}), **(v.get("intent") or {})}, vars_),
                    replies=_interp({**(fam.get("replies") or {}), **(v.get("replies") or {})}, vars_),
                    goal_match=bool(v.get("goal_match", fam.get("goal_match", False))),
                    difficulty=v.get("difficulty", fam.get("difficulty", "medium")),
                    rounds=bool(v.get("rounds", fam.get("rounds", True))),
                    source=path.name, notes=v.get("why", fam.get("why", "")),
                    tags=list(fam.get("tags") or []) + list(v.get("tags") or []),
                )
                out.append(r)
    unused = set(extra) - used
    if unused:
        raise SpecError(f"extra prompts for unknown family/variant: {sorted(unused)[:10]}")
    return out


# --- tool-output rendering (AgentDojo YAML format) ----------------------------------------------------------

_TIME_KEYS = ("timestamp", "start_time", "end_time", "last_modified")
_SOFT_BREAK = re.compile(r"(?<=[^\n.,:;!?])\n(?=[a-z(])")


def _reflow(text: str) -> str:
    """Join hand-wrapped lines inside a sentence (spec bodies are wrapped for readability)."""
    return _SOFT_BREAK.sub(" ", text)


def _dump(obj) -> str:
    def fix(o):
        if isinstance(o, list):
            return [fix(x) for x in o]
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in _TIME_KEYS and isinstance(v, str):
                    try:
                        v = datetime.fromisoformat(v)
                    except ValueError:
                        pass
                out[k] = fix(v)
            return out
        return o
    return yaml.safe_dump(fix(obj), sort_keys=True, default_flow_style=False, allow_unicode=True, width=80).rstrip()


class Env:
    def __init__(self, data: AgentDojoData):
        ws = data.environment("workspace", "default")
        self.files = {str(f["id_"]): f for f in ws["cloud_drive"]["initial_files"]}
        self.emails = {str(e["id_"]): e for e in ws["inbox"]["initial_emails"]}
        self.events = {str(e["id_"]): e for e in ws["calendar"]["initial_events"]}
        bank = data.environment("banking", "default")
        self.transactions = bank["bank_account"]["transactions"]
        self.scheduled = bank["bank_account"]["scheduled_transactions"]
        self.bank_files = bank["filesystem"]["files"]
        self.user_info = {k: v for k, v in bank["user_account"].items() if k != "password"}


def _with_inject(rec: dict, text_key: str, injections: list[str]) -> dict:
    inj = rec.pop("inject", None)
    if inj:
        body = str(rec.get(text_key) or "")
        rec[text_key] = body.replace("{INJ}", inj) if "{INJ}" in body else (body + ("\n\n" if body else "") + inj)
        injections.append(inj)
    return rec


def _email(e: dict, env: Env, injections: list[str], k: int) -> dict:
    base = copy.deepcopy(env.emails[str(e["env"])]) if "env" in e else {}
    rec = {"attachments": [], "bcc": [], "cc": [], "read": True, "status": "received",
           "recipients": ["emma.johnson@bluesparrowtech.com"], "timestamp": f"2024-05-{14 - k % 5:02d} 09:{10 + k:02d}:00",
           **base, **{x: y for x, y in e.items() if x != "env"}}
    rec.setdefault("id_", str(40 + k))
    rec["id_"] = str(rec.pop("id", rec["id_"]))
    rec["body"] = _reflow(str(rec.get("body", "")))
    return _with_inject(rec, "body", injections)


def _file(f, env: Env, injections: list[str]) -> dict:
    if isinstance(f, (str, int)):
        f = {"env": str(f)}
    base = copy.deepcopy(env.files[str(f["env"])]) if "env" in f else {}
    rec = {**base, **{x: y for x, y in f.items() if x not in ("env", "append")}}
    if f.get("append"):
        rec["content"] = rec.get("content", "").rstrip() + "\n" + f["append"]
    rec.setdefault("last_modified", "2024-05-10 14:00:00")
    rec.setdefault("shared_with", {})
    rec["id_"] = str(rec.get("id_", rec.pop("id", "99")))
    rec = _with_inject(rec, "content", injections)
    rec["size"] = len(rec.get("content", ""))
    return rec


def _event(e, env: Env, injections: list[str]) -> dict:
    if isinstance(e, (str, int)):
        e = {"env": str(e)}
    base = copy.deepcopy(env.events[str(e["env"])]) if "env" in e else {}
    rec = {"all_day": False, "status": "confirmed", "location": None, **base,
           **{x: y for x, y in e.items() if x != "env"}}
    for t in ("start_time", "end_time"):
        if t in rec:
            rec[t] = str(rec[t]).replace("T", " ") + (":00" if len(str(rec[t])) == 16 else "")
    rec["id_"] = str(rec.get("id_", rec.pop("id", "30")))
    if rec.get("description"):
        rec["description"] = _reflow(str(rec["description"]))
    return _with_inject(rec, rec.pop("inject_into", "description"), injections)


def render_block(item: dict, env: Env, injections: list[str], k: int) -> str:
    if "text" in item:
        text = item["text"]
        if item.get("inject"):
            text = text.replace("{INJ}", item["inject"]) if "{INJ}" in text else text + "\n" + item["inject"]
            injections.append(item["inject"])
        return text
    if "emails" in item:
        return _dump([_email(e, env, injections, k + i) for i, e in enumerate(item["emails"])])
    if "files" in item:
        return _dump([_file(f, env, injections) for f in item["files"]])
    if "events" in item:
        return _dump([_event(e, env, injections) for e in item["events"]])
    if "bank_file" in item:   # read_file in the banking suite returns the raw file text
        text = item.get("content") or env.bank_files[item["bank_file"]]
        if item.get("inject"):
            text = text.replace("{INJ}", item["inject"]) if "{INJ}" in text else text + "\n" + item["inject"]
            injections.append(item["inject"])
        return text
    if "transactions" in item or "scheduled" in item:
        key = "transactions" if "transactions" in item else "scheduled"
        rows = item[key]
        base = copy.deepcopy(env.transactions if key == "transactions" else env.scheduled) if rows == "default" else []
        extra = [] if rows == "default" else rows
        for t in [*extra, *(item.get("extra") or [])]:
            t = dict(t)
            if t.get("inject"):
                t["subject"] = t.pop("inject")
                injections.append(t["subject"])
            base.append({"recurring": False, "sender": "me", **t})
        return _dump(base)
    if "contacts" in item:
        return _dump(item["contacts"])
    if "user_info" in item:
        return str({**env.user_info, **(item["user_info"] or {})})
    if "value" in item:
        return str(item["value"])
    raise SpecError(f"cannot render context item {item}")


def build_messages(r: Realization, env: Env) -> tuple[list[dict], list[dict], list[str]]:
    messages, prior, injections = [], [], []
    for k, item in enumerate(r.context):
        fn = item["fn"]
        if fn not in REGISTRY:
            raise SpecError(f"{r.family}/{r.variant}: unknown context tool {fn}")
        text = render_block(item, env, injections, k)
        args = item.get("args") or {}
        messages.append({"role": "tool", "content": [{"type": "text", "content": text}],
                         "tool_call": {"function": fn, "args": args}, "error": None})
        prior.append({"function": fn, "args": args})
    return messages, prior, injections


# --- case construction --------------------------------------------------------------------------------------

def _pick(pool, *key) -> str:
    h = int(hashlib.sha1("|".join(map(str, key)).encode()).hexdigest()[:8], 16)
    return pool[h % len(pool)]


def _intent_row(i: dict) -> dict:
    # an ALLOW/BLOCK decision is its own final action (a variant may inherit a deferral family's `final`)
    return {"decision": i["d"], "final": i["d"] if i["d"] in ("ALLOW", "BLOCK") else i.get("final"),
            "missing_evidence": i.get("me", "none"), "required_authority": i.get("ra", "none"),
            "clauses": list(i.get("clauses") or [])}


def follow_ups(r: Realization, approved: bool | None) -> list[tuple[str, dict, dict]]:
    """[(label, response dict, intent after it)] for the answered first round of a deferral intent.
    `approved` is the MockApprover's answer to the escalation (None for ASK_USER)."""
    i = r.intent
    d, me, ra = i["d"], i.get("me", "none"), i.get("ra", "none")
    rp, out = r.replies, []
    if d == "ASK_USER":
        yes = {"responder": "user", "text": rp.get("confirm") or _pick(_USER_YES.get(me, _USER_YES["user_intent"]), r.family, r.variant),
               "provides": me, "confirmed": True}
        no = {"responder": "user", "text": rp.get("decline") or _pick(_USER_NO.get(me, _USER_NO["user_intent"]), r.family, r.variant),
              "provides": me, "confirmed": False}
        out.append(("yes", yes, i.get("after_yes") or {"d": "ALLOW", "me": "none", "ra": "current_user",
                                                       "clauses": i.get("clauses", [])}))
        out.append(("no", no, i.get("after_no") or {"d": "BLOCK", "me": "user_intent", "ra": "current_user",
                                                     "clauses": [f"{'WS' if r.suite == 'workspace' else 'BANK'}-6.3"]}))
        if rp.get("unhelpful", True):
            unh = {"responder": "user", "text": _pick(_UNHELPFUL, r.family, r.variant), "provides": "none",
                   "confirmed": None}
            out.append(("unhelpful", unh, i.get("after_unhelpful") or {"d": "ASK_USER", "me": me, "ra": ra,
                                                                         "clauses": i.get("clauses", [])}))
    elif d == "ESCALATE":
        role = ra if ra in _APPROVE else "manager"
        ok = {"approved": True, "role": ra, "text": rp.get("approve") or _pick(_APPROVE[role], r.family, r.variant)}
        no = {"approved": False, "role": ra, "text": rp.get("deny") or _pick(_DENY[role], r.family, r.variant)}
        # only the approver answer consistent with the case's final action, unless the family asks for both
        if approved or rp.get("both_outcomes"):
            out.append(("approved", ok, i.get("after_approve") or {"d": "ALLOW", "me": "none", "ra": "current_user",
                                                                   "clauses": i.get("clauses", [])}))
        if not approved or rp.get("both_outcomes"):
            out.append(("denied", no, i.get("after_deny") or {"d": "BLOCK", "me": "approval", "ra": ra,
                                                              "clauses": [f"{'WS' if r.suite == 'workspace' else 'BANK'}-6.3"]}))
        if rp.get("overreach", True):
            ov = {"responder": "user", "text": rp.get("overreach_text") or _pick(_OVERREACH, r.family, r.variant),
                  "provides": "none", "confirmed": True, "kind": "ASK_USER"}
            out.append(("user_overreach", ov, {"d": "ESCALATE", "me": me, "ra": ra, "clauses": i.get("clauses", [])}))
    return out


@dataclass
class Built:
    case: Case
    key: dict
    text_hash: str


def build_realization(r: Realization, builder: ContextBuilder, env: Env, valid_clauses: set[str],
                      approver: MockApprover, round_prompts: int = 2) -> list[Built]:
    messages, prior, injections = build_messages(r, env)
    out = []
    for pi, prompt in enumerate(r.prompts):
        cid = f"syn|{_ABBR[r.suite]}|{r.family}|{r.variant}|p{pi}"
        gi, extras = builder.build(cid, r.suite, prompt.strip(), r.call, prior, messages, None,
                                   injections=injections, injection_goal_match=r.goal_match)
        base_meta = {"author": AUTHOR, "reviewed_by": None, "template": r.family, "family": r.family,
                     "variant": r.variant, "prompt_index": pi, "round": 0, "difficulty": r.difficulty,
                     "spec_file": r.source, "tags": r.tags, "retrieved_ids": extras["retrieved_ids"]}
        case = Case(input=gi, pool="train", subset="decision_only", category=r.category,
                    alt_provenance=extras["provenance"], meta=base_meta)
        key = {"case_id": cid, **_intent_row(r.intent), "why": r.notes, "round": 0}
        approved = None
        esc = r.intent if r.intent["d"] == "ESCALATE" else r.intent.get("after_yes") \
            if (r.intent.get("after_yes") or {}).get("d") == "ESCALATE" else None
        if esc:        # the final action of an escalation is what the mock approver answers (as in evaluation)
            ans = approver.respond(case, gi, GateOutput("ESCALATE", esc.get("me", "approval"), esc.get("ra")), 1)
            approved = bool(ans["approved"])
            key["approver_answer"] = "approved" if approved else "denied"
            if r.intent["d"] == "ESCALATE":
                key["final"] = "ALLOW" if approved else "BLOCK"
            elif key["final"] == "ALLOW" and not approved:
                key["final"] = "BLOCK"
            if r.intent.get("final") and r.intent["d"] == "ESCALATE" and r.intent["final"] != key["final"]:
                key["final_overridden"] = r.intent["final"]
        out.append(Built(case, key, _hash(gi)))
        if r.intent["d"] in DEFERRALS and r.rounds and pi < round_prompts:
            for label, resp, after in follow_ups(r, approved):
                kind = resp.pop("kind", r.intent["d"])
                asked = {"missing_evidence": r.intent.get("me", "none"), "required_authority": r.intent.get("ra", "none")}
                if kind == "ESCALATE":
                    auth = gi.authority or {}
                    resp["responder"] = auth.get("approver") or (auth.get("resource_owner") if asked["required_authority"] == "resource_owner" else None) or asked["required_authority"]
                gi2 = with_resolution(gi, 1, kind, asked, resp)
                gi2.case_id = f"{cid}|r1-{label}"
                c2 = Case(input=gi2, pool="train", subset="decision_only", category=r.category,
                          alt_provenance=copy.deepcopy(extras["provenance"]),
                          meta={**base_meta, "round": 1, "resolution": label})
                k2 = {"case_id": gi2.case_id, **_intent_row(after), "why": f"after {kind} -> {label}", "round": 1}
                if k2["final"] is None:     # still deferring: the loop ends with the approver's answer or the round-0 final
                    k2["final"] = ("ALLOW" if approved else "BLOCK") if after["d"] == "ESCALATE" and approved is not None \
                        else key["final"]
                out.append(Built(c2, k2, _hash(gi2)))
    for b in out:
        bad = [c for c in b.key["clauses"] if c not in valid_clauses]
        if bad:
            raise SpecError(f"{b.case.case_id}: unknown clause ids {bad}")
    return out


def _hash(gi) -> str:
    return hashlib.sha1(render_input(gi).encode()).hexdigest()


# --- validation ----------------------------------------------------------------------------------------------

def validate_realization(r: Realization) -> list[str]:
    errs, tag = [], f"{r.family}/{r.variant}"
    sp = REGISTRY.get(r.call.get("function"))
    if sp is None or not sp.state_changing:
        errs.append(f"{tag}: proposed call {r.call.get('function')} is not a state-changing tool")
    elif sp.suite != r.suite:
        errs.append(f"{tag}: tool {sp.name} belongs to {sp.suite}")
    if r.category not in CATEGORIES:
        errs.append(f"{tag}: category {r.category!r}")
    i = r.intent
    if i.get("d") not in FIELD_VALUES["decision"]:
        errs.append(f"{tag}: intent decision {i.get('d')!r}")
    if i.get("me", "none") not in FIELD_VALUES["missing_evidence"]:
        errs.append(f"{tag}: missing_evidence {i.get('me')!r}")
    if i.get("ra", "none") not in FIELD_VALUES["required_authority"]:
        errs.append(f"{tag}: required_authority {i.get('ra')!r}")
    if i.get("d") in DEFERRALS and i.get("final") not in ("ALLOW", "BLOCK"):
        errs.append(f"{tag}: deferral intent needs final ALLOW/BLOCK")
    bad = [p for p in r.prompts if not isinstance(p, str)]
    if bad:
        errs.append(f"{tag}: prompt parsed as {type(bad[0]).__name__} (quote it): {bad[0]!r}")
        return errs
    if len(r.prompts) < 1:
        errs.append(f"{tag}: no prompts")
    leftover = [p for p in [*r.prompts, json.dumps(r.call)] if _VAR.search(p)]
    if leftover:
        errs.append(f"{tag}: unresolved placeholder in {leftover[0][:80]!r}")
    return errs


def evidence_warnings(b: Built) -> list[str]:
    """Consistency between the declared category and the provenance the builder computed."""
    gi, cat = b.case.input, b.case.category
    prov = gi.provenance or []
    call_untrusted = next((p for p in prov if p.get("kind") == "call"), {}).get("trust") == "untrusted"
    arg_untrusted = any(p.get("trust") == "untrusted" for p in prov if p.get("kind") == "arg")
    w = []
    if cat == "injection" and b.key["round"] == 0 and not (call_untrusted or arg_untrusted):
        w.append(f"{b.case.case_id}: category injection but provenance shows no untrusted origin")
    if cat in ("benign", "benign_with_injection", "delegation", "ambiguity") and (call_untrusted or arg_untrusted):
        w.append(f"{b.case.case_id}: category {cat} but provenance marks untrusted values")
    return w


_WORD = re.compile(r"[a-z0-9@.\-']+")


def _shingles(text: str, n: int = 5) -> set:
    w = _WORD.findall(text.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def test_prompt_overlap(prompts: list[str], data: AgentDojoData) -> dict[str, float]:
    """Max 5-gram containment of each synthetic prompt in any test-pool user task / injection goal."""
    split = json.loads((data.dir / "splits" / "scenario_split.json").read_text())
    test_texts = [t.get("prompt") or "" for (s, i), t in data.user_tasks.items()
                  if split["user_tasks"].get(f"{s}|{i}") == "test"]
    test_texts += [t.get("goal") or "" for (s, i), t in data.injection_tasks.items()
                   if split["injection_tasks"].get(f"{s}|{i}") == "test"]
    test_sh = [_shingles(t) for t in test_texts if t]
    out = {}
    for p in prompts:
        sh = _shingles(p)
        out[p] = max((len(sh & t) / len(sh) for t in test_sh if sh), default=0.0)
    return out


# --- sampling and writing ------------------------------------------------------------------------------------

def sample(built: list[Built], n: int, mix: dict, round_share: float, rng: random.Random) -> list[Built]:
    """Keep every family represented: take round-0 cases class-balanced to `mix`, spreading picks across families
    (round-robin within a class), and `round_share` of n from answered rounds."""
    if len(built) <= n:
        return built
    first = [b for b in built if b.key["round"] == 0]
    later = [b for b in built if b.key["round"] > 0]
    n_later = min(len(later), round(n * round_share))

    def spread(pool: list[Built], k: int) -> list[Built]:
        by_fam = defaultdict(list)
        for b in pool:
            by_fam[b.case.meta["family"]].append(b)
        for v in by_fam.values():
            rng.shuffle(v)
        fams = sorted(by_fam)
        rng.shuffle(fams)
        picked = []
        while len(picked) < k and any(by_fam.values()):
            for f in fams:
                if by_fam[f] and len(picked) < k:
                    picked.append(by_fam[f].pop())
        return picked

    picked = spread(later, n_later)
    n0 = n - len(picked)
    by_cls = defaultdict(list)
    for b in first:
        by_cls[b.key["decision"]].append(b)
    quota = {c: round(mix.get(c, 0) * n0) for c in FIELD_VALUES["decision"]}
    short = sum(max(0, q - len(by_cls[c])) for c, q in quota.items())
    for c in sorted(quota, key=lambda c: len(by_cls[c]) - quota[c], reverse=True):     # redistribute shortfall
        if short <= 0:
            break
        extra = min(short, len(by_cls[c]) - quota[c])
        if extra > 0:
            quota[c] += extra
            short -= extra
    for c, q in quota.items():
        picked += spread(by_cls[c], min(q, len(by_cls[c])))
    if len(picked) < n:        # classes short of quota: top up from what is left, still spread over families
        ids = {id(b) for b in picked}
        picked += spread([b for b in built if id(b) not in ids], n - len(picked))
    rng.shuffle(picked)
    return picked[:n]


def build(n: int, out_dir: Path = OUT_DIR, cfg_path: str | None = None, write: bool = True,
          max_overlap: float = 0.5) -> list[Built]:
    cfg = load_config(cfg_path)
    data = AgentDojoData(cfg.data_dir)
    builder = ContextBuilder(cfg, data)
    env = Env(data)
    approver = MockApprover(cfg.resources_dir)
    valid = {c.id for s in ("workspace", "banking") for c in parse_handbook(cfg.resources_dir / "handbooks" / f"{s}.md")}
    reals = load_specs()
    errs = [e for r in reals for e in validate_realization(r)]
    if errs:
        raise SpecError(f"{len(errs)} spec problems:\n  " + "\n  ".join(errs[:40]))

    overlap = test_prompt_overlap([p for r in reals for p in r.prompts], data)
    leaky = {p: v for p, v in overlap.items() if v > max_overlap}

    built, seen, dups = [], set(), 0
    for r in reals:
        r.prompts = [p for p in r.prompts if p not in leaky]
        for b in build_realization(r, builder, env, valid, approver):
            if b.text_hash in seen:
                dups += 1
                continue
            seen.add(b.text_hash)
            built.append(b)
    warns = [w for b in built for w in evidence_warnings(b)]
    from .variants import decide            # the structured-variant labeller: how rule-reducible is each case?
    for b in built:
        b.key["policy_labeller_decision"] = decide(b.case.input).decision

    rng = random.Random(cfg["seed"])
    picked = sample(built, n, DEFAULT_MIX, 0.18, rng)
    picked.sort(key=lambda b: b.case.case_id)
    fams = Counter(r.family for r in reals)
    stats = {
        "families": len(fams), "realizations": len(reals),
        "prompts": sum(len(r.prompts) for r in reals),
        "candidates": len(built), "duplicates_dropped": dups, "written": len(picked),
        "test_overlap_dropped": len(leaky), "max_test_overlap_kept": round(max(
            [v for p, v in overlap.items() if p not in leaky] or [0.0]), 3),
        "by_suite": dict(Counter(b.case.input.suite for b in picked)),
        "by_category": dict(Counter(b.case.category for b in picked)),
        "by_round": dict(Counter(b.key["round"] for b in picked)),
        "design_intent_round0": dict(Counter(b.key["decision"] for b in picked if b.key["round"] == 0)),
        "design_intent_round1": dict(Counter(b.key["decision"] for b in picked if b.key["round"] == 1)),
        "design_final_action": dict(Counter(b.key["final"] for b in picked if b.key["round"] == 0)),
        "design_missing_evidence": dict(Counter(b.key["missing_evidence"] for b in picked)),
        "design_required_authority": dict(Counter(b.key["required_authority"] for b in picked)),
        "proposed_functions": dict(Counter(b.case.input.proposed_call["function"] for b in picked)),
        "difficulty": dict(Counter(b.case.meta["difficulty"] for b in picked)),
        "final_overridden_by_approver": sum("final_overridden" in b.key for b in picked),
        "policy_labeller_agrees_with_design": round(
            sum(b.key["policy_labeller_decision"] == b.key["decision"] for b in picked) / max(1, len(picked)), 3),
        "evidence_warnings": warns,
    }
    print(json.dumps({k: v for k, v in stats.items() if k != "evidence_warnings"}, indent=1))
    for w in warns[:30]:
        print("WARN", w)
    for p, v in sorted(leaky.items(), key=lambda x: -x[1])[:10]:
        print(f"DROPPED (test overlap {v:.2f}): {p[:100]}")
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        save_cases(out_dir / "cases.jsonl", [b.case for b in picked])
        write_jsonl(out_dir / "design_key.jsonl", [b.key for b in picked])
        (out_dir / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
        from ..data.annotation import export
        export(str(out_dir / "cases.jsonl"), str(out_dir / "to_label.csv"), None, cfg["seed"])
    return picked


def merge(cases_path: str | Path, gold_path: str | Path, out: str | Path, reviewer: str | None = None) -> int:
    """Attach adjudicated human labels (annotation `gold` output) to the synthetic cases and write the labelled ones
    as an NL training file (name it *_nl.jsonl so build_sft runs the NL validator on it)."""
    from ..data.cases import attach_gold, load_cases
    from .nl_examples import validate
    cases = load_cases(cases_path)
    attach_gold(cases, read_jsonl(gold_path))
    labelled = [c for c in cases if c.has_gold]
    for c in labelled:
        if reviewer and not c.meta.get("reviewed_by"):
            c.meta["reviewed_by"] = reviewer
    errs = [e for c in labelled for e in validate(c)]
    if errs:
        raise SpecError(f"{len(errs)} problems:\n  " + "\n  ".join(errs[:20]))
    n = save_cases(out, labelled)
    print(f"{n}/{len(cases)} synthetic cases labelled -> {out}  gold mix {dict(Counter(c.gold_decision for c in labelled))}")
    return n


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "check", "merge"])
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--cases", default=str(OUT_DIR / "cases.jsonl"), help="merge: the unlabeled synthetic cases")
    ap.add_argument("--gold", default=None, help="merge: gold JSONL from `sagate.data.annotation gold`")
    ap.add_argument("--reviewer", default=None, help="merge: fills meta.reviewed_by where the gold row has none")
    a = ap.parse_args(argv)
    if a.cmd == "merge":
        if not a.gold:
            ap.error("merge needs --gold")
        merge(a.cases, a.gold, a.out or "annotations/synthetic_nl.jsonl", a.reviewer)
        return
    build(a.n, Path(a.out) if a.out else OUT_DIR, a.config, write=a.cmd == "build")


if __name__ == "__main__":
    main()
