"""Information-flow labels (PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED) and the high_to_low check.

Supporting evidence only (proposal §4). Labels come from resources/sensitivity/<suite>.yaml; destination clearance
is derived from the authority registry (who the destination is).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..gate.schema import LABEL_ORDER
from .tools_registry import ToolSpec

CLEARANCE = {  # destination class -> highest label it may receive without approval
    "self": "RESTRICTED",
    "internal": "CONFIDENTIAL",
    "client": "INTERNAL",
    "approved_payee": "INTERNAL",
    "personal": "PUBLIC",
    "unknown": "PUBLIC",
    "new_payee": "PUBLIC",
    "bank": "RESTRICTED",
}
_MIN_LINE = 30   # a copied line of at least this many chars marks the file's content as present


def rank(label: str) -> int:
    return LABEL_ORDER.index(label)


def max_label(labels) -> str:
    labels = list(labels)
    return max(labels, key=rank) if labels else "PUBLIC"


def min_label(labels) -> str:
    labels = list(labels)
    return min(labels, key=rank) if labels else "RESTRICTED"


class SensitivityLabeler:
    def __init__(self, resources_dir: str | Path, suite: str, env: dict):
        with open(Path(resources_dir) / "sensitivity" / f"{suite}.yaml") as f:
            self.cfg = yaml.safe_load(f)
        self.suite = suite
        self.default = self.cfg.get("default_label", "INTERNAL")
        self.markers = self.cfg.get("markers", [])
        self.file_labels = {str(k): v for k, v in (self.cfg.get("files") or {}).items()}
        self.file_content: dict[str, str] = {}
        if suite == "workspace":
            for f in env.get("cloud_drive", {}).get("initial_files", []):
                self.file_content[str(f["id_"])] = f.get("content", "")

    def file_label(self, file_id, created: dict | None = None) -> str:
        """Label of a drive file. Files created earlier in the same run (not in the environment) are labelled
        by the content the agent wrote into them."""
        fid = str(file_id)
        if fid in self.file_labels:
            return self.file_labels[fid]
        if created and fid in created:
            return self.content_label(created[fid])[0]
        return self.default

    def content_label(self, text: str) -> tuple[str, list[str]]:
        """Label of free text by markers and by lines copied from labelled files."""
        if not text:
            return "PUBLIC", []
        found, basis = ["PUBLIC"], []
        low = text.lower()
        for m in self.markers:
            if m["text"].lower() in low:
                found.append(m["label"]); basis.append(f"marker:{m['what']}")
        for fid, content in self.file_content.items():
            lab = self.file_label(fid)
            if rank(lab) <= rank("PUBLIC"):
                continue
            for line in content.splitlines():
                line = line.strip()
                if len(line) >= _MIN_LINE and line.lower() in low:
                    found.append(lab); basis.append(f"content_of:file:{fid}")
                    break
        return max_label(found), basis

    def created_files(self, prior_calls: list[dict]) -> dict[str, str]:
        """New drive ids -> content for create_file calls earlier in the run (ids continue after the env's)."""
        out, next_id = {}, max((int(k) for k in self.file_content if k.isdigit()), default=-1) + 1
        for c in prior_calls or []:
            if c.get("function") == "create_file":
                out[str(next_id)] = str((c.get("args") or {}).get("content") or "")
                next_id += 1
        return out

    def assess(self, call: dict, spec: ToolSpec, dest_classes: list[str], prior_calls: list[dict] = ()) -> dict:
        """{resource, destination, flow, basis}. `dest_classes` come from AuthorityRegistry.destinations()."""
        args = call.get("args", {}) or {}
        created = self.created_files(list(prior_calls)) if self.suite == "workspace" else {}
        labels, basis = [], []
        if spec.action == "account_change":
            labels.append((self.cfg.get("account_change") or {}).get(spec.name, self.default))
        if spec.resource_arg and spec.action in ("disclose", "delete", "modify") and self.suite == "workspace":
            res = args.get(spec.resource_arg)
            if spec.resource_arg == "attachments":
                for a in res or []:
                    if isinstance(a, dict) and a.get("file_id") is not None:
                        labels.append(self.file_label(a["file_id"], created)); basis.append(f"attachment:file:{a['file_id']}")
            elif spec.resource_arg == "file_id" and res is not None:
                labels.append(self.file_label(res, created)); basis.append(f"file:{res}")
        text = " ".join(str(args.get(a) or "") for a in spec.content_args)
        lab, b = self.content_label(text)
        labels.append(lab); basis += b
        resource = max_label(labels)
        if not dest_classes:
            return {"resource": resource, "destination": None, "flow": "n/a", "basis": basis}
        destination = min_label(CLEARANCE.get(c, "PUBLIC") for c in dest_classes)
        flow = "high_to_low" if rank(resource) > rank(destination) else "ok"
        return {"resource": resource, "destination": destination, "flow": flow, "basis": basis}
