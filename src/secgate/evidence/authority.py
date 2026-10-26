"""Authority registry: direct structured lookup over resources/authority/<suite>.yaml (no retrieval).

`assess()` states facts — who owns the resource, who receives it and how they relate to the user, whether the
current user may authorize the action, which role is required and on what basis, whether policy prohibits it.
The decision itself is left to the gate. Authority is never read from tool outputs or documents.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from ..gate.schema import REQUIRED_AUTHORITY, label_rank
from .tools import ToolSpec

_ROLE_ORDER = list(REQUIRED_AUTHORITY)   # none < current_user < resource_owner < manager < security_admin


def stronger(a: str, b: str) -> str:
    return a if _ROLE_ORDER.index(a) >= _ROLE_ORDER.index(b) else b


def as_list(v: Any) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AuthorityRegistry:
    def __init__(self, resources_dir: str | Path, suite: str, env: dict):
        with open(Path(resources_dir) / "authority" / f"{suite}.yaml", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.suite = suite
        self.current_user = self.cfg["current_user"]
        me = self.cfg["principals"][self.current_user]
        if suite == "workspace":
            self.user_email = me["email"].lower()
            self.org_domains = [d.lower() for d in self.cfg.get("org_domains", [])]
            self.files = {str(f["id_"]): f for f in env.get("cloud_drive", {}).get("initial_files", [])}
        else:
            self.user_iban = me["iban"]
            self.payees: dict[str, str] = {}
            for iban, info in (self.cfg.get("known_payees") or {}).items():
                self.payees[iban.lower()] = iban
                for alias in (info or {}).get("aliases", []):
                    self.payees[alias.lower()] = iban
            acct = env.get("bank_account", {})
            self.scheduled = {int(t["id"]): t for t in acct.get("scheduled_transactions", [])}

    # --- who receives it ----------------------------------------------------------------------------------
    def relation(self, address: str) -> str:
        """self | internal | client | personal | unknown (workspace addresses)."""
        a = str(address).strip().lower()
        if a == self.user_email:
            return "self"
        if a.rsplit("@", 1)[-1] in self.org_domains:
            return "internal"
        for rel, patterns in (self.cfg.get("known_external") or {}).items():
            if any(fnmatch.fnmatch(a, p.lower()) for p in patterns):
                return rel
        return "unknown"

    def payee(self, recipient: Any) -> tuple[str, bool]:
        """(IBAN, known?) for a banking recipient given as IBAN or alias."""
        r = str(recipient).strip()
        iban = self.payees.get(r.lower())
        return (iban, True) if iban else (r, False)

    def recipients(self, call: dict, sp: ToolSpec) -> list[dict]:
        args = call.get("args") or {}
        out = []
        for name in sp.destination_args:
            for v in as_list(args.get(name)):
                if v in (None, ""):
                    continue
                if self.suite == "workspace":
                    out.append({"value": str(v), "relation": self.relation(v)})
                else:
                    iban, known = self.payee(v)
                    out.append({"value": iban, "relation": "known_payee" if known else "new_payee"})
        return out

    def approver_for(self, role: str, owner: str | None = None) -> str | None:
        if role == "resource_owner":
            return owner
        return (self.cfg.get("approvers") or {}).get(role)

    # --- assessment ---------------------------------------------------------------------------------------
    def assess(self, call: dict, sp: ToolSpec, sensitivity: dict) -> dict:
        out = {
            "principal": self.current_user,
            "action_class": sp.action_class,
            "resource": None,
            "resource_owner": None,
            "user_permission": None,
            "recipients": self.recipients(call, sp),
            "required_authority": "current_user" if sp.state_changing else "none",
            "basis": [],
            "prohibited": False,
            "approver": None,
            "approvals": [],
        }
        if sp.state_changing:
            if self.suite == "workspace":
                self._workspace(call, sp, sensitivity, out)
            else:
                self._banking(call, sp, out)
        out["user_may_authorize"] = out["required_authority"] in ("none", "current_user") and not out["prohibited"]
        if not out["user_may_authorize"] and not out["prohibited"]:
            out["approver"] = self.approver_for(out["required_authority"], out["resource_owner"])
        return out

    def _need(self, out: dict, role: str, basis: str) -> None:
        if role == "prohibited":
            out["prohibited"] = True
        else:
            out["required_authority"] = stronger(out["required_authority"], role)
        if basis not in out["basis"]:
            out["basis"].append(basis)

    def _file(self, file_id: Any, out: dict) -> bool:
        """Record a drive file as the resource; True when someone else owns it."""
        f = self.files.get(str(file_id))
        out["resource"] = f"file:{file_id}" + (f" ({f['filename']})" if f else "")
        owner = (f or {}).get("owner", self.user_email).lower()
        if owner == self.user_email:
            out["resource_owner"], out["user_permission"] = "current_user", "owner"
            return False
        out["resource_owner"] = owner
        out["user_permission"] = ((f or {}).get("shared_with") or {}).get(self.user_email, "none")
        return True

    def _workspace(self, call: dict, sp: ToolSpec, sens: dict, out: dict) -> None:
        args = call.get("args") or {}
        others = self.cfg.get("others_resources") or {}
        owned_by_other = False
        if sp.resource_arg == "file_id" and args.get("file_id") is not None:
            owned_by_other = self._file(args["file_id"], out)
        elif sp.resource_arg == "attachments":
            ids = [a.get("file_id") for a in as_list(args.get("attachments")) if isinstance(a, dict)]
            ids = [i for i in ids if i is not None]
            if ids:
                owned_by_other = any([self._file(i, {}) for i in ids])
                self._file(ids[0], out)
        elif sp.resource_arg == "email_id":
            out["resource"], out["resource_owner"] = f"email:{args.get('email_id')}", "current_user"
        elif sp.resource_arg == "event_id":
            out["resource"], out["resource_owner"] = f"event:{args.get('event_id')}", "current_user"
        elif sp.resource_arg == "filename":
            out["resource"], out["resource_owner"] = f"new_file:{args.get('filename')}", "current_user"

        if sp.action_class in ("disclose", "invite"):
            label = sens.get("data_label", "PUBLIC")
            caps = self.cfg.get("disclosure_caps") or {}
            above = self.cfg.get("disclosure_above_cap") or {}
            for r in out["recipients"]:
                rel = r["relation"]
                if label_rank(label) <= label_rank(caps.get(rel, "PUBLIC")):
                    continue
                role = (above.get(label) or {}).get(rel, "manager")
                if role == "manager" and owned_by_other and label == "CONFIDENTIAL":
                    role = "resource_owner"
                basis = {"RESTRICTED": "disclose_restricted_internal" if rel == "internal" else "disclose_restricted",
                         "CONFIDENTIAL": "disclose_confidential_external",
                         "INTERNAL": "internal_data_to_unknown_recipient"}.get(label, "disclose_above_cap")
                self._need(out, role, basis)
            if sp.name == "share_file" and str(args.get("permission", "r")).lower() in ("rw", "w", "write") \
                    and owned_by_other:
                self._need(out, others.get("share_write", "resource_owner"), "share_write")
        elif sp.action_class == "delete" and owned_by_other:
            self._need(out, others.get("delete", "resource_owner"), "delete_others_resource")
        elif sp.action_class == "modify" and owned_by_other and out["user_permission"] in ("r", "none"):
            self._need(out, others.get("modify_readonly", "resource_owner"), "modify_readonly")

    def _banking(self, call: dict, sp: ToolSpec, out: dict) -> None:
        args = call.get("args") or {}
        limits = self.cfg.get("transfer_limits") or {}
        out["resource"], out["resource_owner"] = f"account:{self.user_iban}", "current_user"
        if sp.action_class == "transfer":
            amount = to_float(args.get("amount"))
            new_payee = any(r["relation"] == "new_payee" for r in out["recipients"])
            if sp.name == "update_scheduled_transaction":
                tid = to_float(args.get("id"))
                existing = self.scheduled.get(int(tid)) if tid is not None else None
                out["resource"] = f"scheduled_transaction:{args.get('id')}"
                if args.get("recipient") and new_payee:
                    self._need(out, self.cfg.get("standing_order_new_recipient", "manager"),
                               "standing_order_new_recipient")
                if not args.get("recipient") and existing:
                    new_payee = not self.payee(existing["recipient"])[1]
                if amount is None and existing:
                    amount = to_float(existing.get("amount"))
            if amount is not None:
                limit = limits.get("new_payee_max", 500) if new_payee else limits.get("known_payee_max", 1000)
                if amount > limits.get("manager_max", 5000):
                    self._need(out, "prohibited", "transfer_over_manager_max")
                elif amount > limit:
                    self._need(out, "manager", "transfer_over_limit")
        elif sp.action_class == "account_change":
            changes = self.cfg.get("account_changes") or {}
            if sp.name == "update_user_info":
                out["resource"] = "account:personal_details"
                for field, v in args.items():
                    if v in (None, ""):
                        continue
                    role = (changes.get("update_user_info") or {}).get(field, "current_user")
                    if role != "current_user":
                        self._need(out, role, "identity_change")
            else:
                out["resource"] = "account:password"
