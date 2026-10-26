"""Authority registry: direct structured lookup over resources/authority/<suite>.yaml (ARCHITECTURE.md §5.3).

Authority is read only from this registry and from MockApprover responses — never from untrusted content.
`assess()` states facts (who owns the resource, who receives it, whether the current user may authorize, which
role is required and why); the decision itself is left to the gate.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .sensitivity import rank
from .tools_registry import ToolSpec

ROLE_STRENGTH = ["none", "current_user", "resource_owner", "manager", "security_admin"]


def _stronger(a: str, b: str) -> str:
    return a if ROLE_STRENGTH.index(a) >= ROLE_STRENGTH.index(b) else b


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AuthorityRegistry:
    def __init__(self, resources_dir: str | Path, suite: str, env: dict):
        with open(Path(resources_dir) / "authority" / f"{suite}.yaml") as f:
            self.cfg = yaml.safe_load(f)
        self.suite = suite
        self.env = env
        self.current_user = self.cfg["current_user"]
        self.principals = self.cfg.get("principals", {})
        if suite == "workspace":
            self.user_email = self.principals[self.current_user]["email"].lower()
            self.files = {str(f["id_"]): f for f in env.get("cloud_drive", {}).get("initial_files", [])}
        else:
            self.user_iban = self.principals[self.current_user].get("iban")
            self.payees = {}
            for iban, info in (self.cfg.get("approved_payees") or {}).items():
                self.payees[iban.lower()] = iban
                for a in (info or {}).get("aliases", []):
                    self.payees[a.lower()] = iban
            self.scheduled = {int(t["id"]): t for t in env.get("bank_account", {}).get("scheduled_transactions", [])}

    # --- destinations ---------------------------------------------------------------------------------
    def classify_address(self, addr: str) -> str:
        a = str(addr).strip().lower()
        if a == self.user_email:
            return "self"
        domain = a.rsplit("@", 1)[-1]
        if domain in [d.lower() for d in self.cfg.get("org_domains", [])]:
            return "internal"
        ext = self.cfg.get("approved_external", {})
        for cls in ("client", "personal"):
            if any(fnmatch.fnmatch(a, p.lower()) for p in ext.get(cls, [])):
                return cls
        return "unknown"

    def resolve_payee(self, recipient: Any) -> tuple[str, bool]:
        r = str(recipient).strip()
        iban = self.payees.get(r.lower())
        return (iban, True) if iban else (r, False)

    def destinations(self, call: dict, spec: ToolSpec) -> list[tuple[str, str]]:
        """[(destination class, value)] for the call's destination args."""
        args = call.get("args", {}) or {}
        out = []
        for a in spec.destination_args:
            for v in _as_list(args.get(a)):
                if v in (None, ""):
                    continue
                if self.suite == "workspace":
                    out.append((self.classify_address(v), str(v)))
                else:
                    iban, ok = self.resolve_payee(v)
                    out.append(("approved_payee" if ok else "new_payee", iban))
        if self.suite == "banking" and spec.action == "account_change":
            out.append(("bank", "Blue Sparrow Bank"))
        return out

    # --- assessment -----------------------------------------------------------------------------------
    def assess(self, call: dict, spec: ToolSpec, sensitivity: dict | None) -> dict:
        dests = self.destinations(call, spec)
        base = {
            "principal": self.current_user,
            "principal_role": "current_user",
            "action": spec.action,
            "resource": None,
            "resource_owner": None,
            "affected_party": [f"{c}:{v}" for c, v in dests],
            "user_may_authorize": True,
            "required_role": "current_user",
            "approver": None,
            "basis": [],
            "prior_approvals": [],
        }
        if not spec.state_changing:
            base["required_role"] = "none"
            return base
        if self.suite == "workspace":
            self._assess_workspace(call, spec, dests, sensitivity or {}, base)
        else:
            self._assess_banking(call, spec, dests, base)
        role = base["required_role"]
        base["user_may_authorize"] = role in ("none", "current_user")
        if role in ("manager", "security_admin"):
            base["approver"] = (self.cfg.get("approvers") or {}).get(role)
        elif role == "resource_owner":
            base["approver"] = base["resource_owner"]
        return base

    def _require(self, out: dict, role: str, basis: str) -> None:
        out["required_role"] = _stronger(out["required_role"], role)
        if basis not in out["basis"]:
            out["basis"].append(basis)

    def _assess_workspace(self, call, spec, dests, sens, out) -> None:
        args = call.get("args", {}) or {}
        rules = self.cfg.get("user_rules", {})
        file_id = None
        if spec.resource_arg == "file_id" and args.get("file_id") is not None:
            file_id = str(args["file_id"])
        elif spec.resource_arg == "attachments":
            ids = [str(a["file_id"]) for a in _as_list(args.get("attachments")) if isinstance(a, dict) and "file_id" in a]
            file_id = ids[0] if ids else None
        if file_id is not None:
            f = self.files.get(file_id)
            out["resource"] = f"file:{file_id}" + (f" ({f['filename']})" if f else "")
            owner = (f or {}).get("owner", self.user_email).lower()
            out["resource_owner"] = "current_user" if owner == self.user_email else owner
        elif spec.resource_arg == "email_id" and args.get("email_id") is not None:
            out["resource"], out["resource_owner"] = f"email:{args['email_id']}", "current_user"
        elif spec.resource_arg == "event_id" and args.get("event_id") is not None:
            out["resource"], out["resource_owner"] = f"event:{args['event_id']}", "current_user"
        elif spec.resource_arg == "filename":
            out["resource"], out["resource_owner"] = f"new_file:{args.get('filename')}", "current_user"
        owned_by_other = out["resource_owner"] not in (None, "current_user")
        my_perm = None
        if owned_by_other and file_id in self.files:
            my_perm = (self.files[file_id].get("shared_with") or {}).get(self.user_email)

        if spec.action == "disclose":
            label = sens.get("resource", "PUBLIC")
            caps = rules.get("disclose", {})
            cap_for = {"self": "RESTRICTED", "internal": caps.get("max_label_internal", "CONFIDENTIAL"),
                       "client": caps.get("max_label_client", "INTERNAL")}
            for cls, _ in dests:
                cap = cap_for.get(cls, caps.get("max_label_other", "PUBLIC"))
                if rank(label) <= rank(cap):
                    continue
                if label == "RESTRICTED":
                    self._require(out, "security_admin", "disclose_restricted")
                elif label == "CONFIDENTIAL" and cls != "internal":
                    if owned_by_other:
                        self._require(out, "resource_owner", "disclose_confidential_external")
                    else:
                        self._require(out, "manager", "disclose_confidential_external")
                else:
                    self._require(out, "manager", "disclose_internal_unknown_external")
            if spec.name == "share_file" and str(args.get("permission", "r")).lower() in ("rw", "w", "write") \
                    and owned_by_other and not rules.get("share_write_on_others_files", False):
                self._require(out, "resource_owner", "share_write_on_others_files")
        elif spec.action == "delete":
            if owned_by_other and not rules.get("delete_others_resources", False):
                self._require(out, "resource_owner", "delete_others_resources")
        elif spec.action == "modify":
            if owned_by_other and my_perm == "r" and not rules.get("modify_readonly_shared", False):
                self._require(out, "resource_owner", "modify_readonly_shared")

    def _assess_banking(self, call, spec, dests, out) -> None:
        args = call.get("args", {}) or {}
        rules = self.cfg.get("user_rules", {})
        tr = rules.get("transfer", {})
        mgr_max = ((self.cfg.get("approver_policy") or {}).get("manager") or {}).get("manager_max")
        out["resource"] = f"account:{self.user_iban}"
        out["resource_owner"] = "current_user"
        if spec.action == "transfer":
            amount = _to_float(args.get("amount"))
            existing = None
            if spec.name == "update_scheduled_transaction":
                sid = _to_float(args.get("id"))
                existing = self.scheduled.get(int(sid)) if sid is not None else None
                out["resource"] = f"scheduled_transaction:{args.get('id')}"
                if amount is None and existing:
                    amount = _to_float(existing.get("amount"))
            new_payee = any(c == "new_payee" for c, _ in dests)
            if spec.name == "update_scheduled_transaction" and args.get("recipient") and new_payee:
                self._require(out, rules.get("standing_order_new_recipient", "manager"),
                              "standing_order_new_recipient")
            if amount is not None:
                limit = tr.get("new_payee_max", 500) if new_payee else tr.get("approved_payee_max", 1500)
                if spec.name == "update_scheduled_transaction" and not args.get("recipient") and existing:
                    limit = tr.get("approved_payee_max", 1500)   # recipient unchanged: payee already set up
                if amount > limit:
                    self._require(out, "manager", "transfer_over_limit")
                if mgr_max is not None and amount > mgr_max:
                    out["basis"].append("transfer_over_manager_max")
        elif spec.action == "account_change":
            out["resource"] = f"account_settings:{spec.name}"
