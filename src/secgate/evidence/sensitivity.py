"""Information-flow labels (PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED): what label the data in a call
carries, how cleared its destination is, and whether the flow goes from high to low.

The data label of a call is the highest label of (a) the resource it acts on or attaches and (b) any labelled
resource whose text was copied into its content arguments (matched by text fingerprints) or any secret marker
it contains. Deterministic, supporting evidence only.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..gate.schema import LABELS, label_rank
from .provenance import norm
from .tools import ToolSpec

CLEARANCE = {"self": "RESTRICTED", "internal": "CONFIDENTIAL", "client": "INTERNAL", "personal": "INTERNAL",
             "unknown": "PUBLIC", "known_payee": "PUBLIC", "new_payee": "PUBLIC"}
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_FINGERPRINT_MIN = 30


def max_label(labels) -> str:
    labels = [l for l in labels if l in LABELS]
    return max(labels, key=label_rank) if labels else "PUBLIC"


def _fingerprints(text: str) -> list[str]:
    """Normalised lines / sentences long enough that a match means the text was copied."""
    pieces = re.split(r"[\n\r]+|(?<=[.!?])\s+", text or "")
    return [p for p in (norm(x) for x in pieces) if len(p) >= _FINGERPRINT_MIN]


class SensitivityLabeler:
    def __init__(self, resources_dir: str | Path, suite: str, env: dict):
        with open(Path(resources_dir) / "sensitivity" / f"{suite}.yaml", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.suite = suite
        self.default = self.cfg.get("default", "INTERNAL")
        self.markers = {norm(k): v for k, v in (self.cfg.get("markers") or {}).items()}
        self.file_labels = {str(k): v for k, v in (self.cfg.get("files") or {}).items()}
        self.prints: list[tuple[str, str, str]] = []            # (fingerprint, label, resource)
        if suite == "workspace":
            for f in env.get("cloud_drive", {}).get("initial_files", []):
                lab = self.file_labels.get(str(f["id_"]), self.default)
                self.prints += [(p, lab, f"file:{f['id_']}") for p in _fingerprints(f.get("content", ""))]
            email_labels = {str(k): v for k, v in (self.cfg.get("emails") or {}).items()}
            for e in env.get("inbox", {}).get("initial_emails", []):
                lab = email_labels.get(str(e["id_"]))
                if lab:
                    self.prints += [(p, lab, f"email:{e['id_']}") for p in _fingerprints(e.get("body", ""))]
        else:
            for name, text in (env.get("filesystem", {}).get("files") or {}).items():
                lab = self.file_labels.get(name, self.default)
                self.prints += [(p, lab, f"file:{name}") for p in _fingerprints(text)]
        # only labels above PUBLIC matter for copied text
        self.prints = [p for p in self.prints if label_rank(p[1]) > 0]

    def file_label(self, file_id) -> str:
        return self.file_labels.get(str(file_id), self.default)

    def content_label(self, text: str) -> tuple[str, list[str]]:
        """Label of free text from copied fingerprints and markers, with the resources it came from."""
        t = norm(text)
        if not t:
            return "PUBLIC", []
        hits = [(lab, res) for p, lab, res in self.prints if p in t]
        hits += [(lab, f"marker:{m}") for m, lab in self.markers.items() if m in t]
        if self.suite == "banking" and _IBAN.search(text or ""):
            hits.append(("CONFIDENTIAL", "iban_in_text"))
        return max_label(l for l, _ in hits), sorted({r for _, r in hits})

    def assess(self, call: dict, sp: ToolSpec, destination_relations: list[str]) -> dict:
        args = call.get("args") or {}
        sources: list[str] = []
        labels: list[str] = []
        # resource acted on / attached
        if sp.resource_arg == "file_id" and args.get("file_id") is not None and self.suite == "workspace":
            labels.append(self.file_label(args["file_id"]))
            sources.append(f"file:{args['file_id']}")
        if sp.resource_arg == "attachments":
            for a in args.get("attachments") or []:
                if isinstance(a, dict) and a.get("file_id") is not None:
                    labels.append(self.file_label(a["file_id"]))
                    sources.append(f"file:{a['file_id']}")
        # copied content
        for name in sp.content_args:
            v = args.get(name)
            if isinstance(v, str):
                if self.suite == "banking":
                    recip = str(args.get("recipient") or "")
                    v = v.replace(recip, " ") if recip else v
                lab, res = self.content_label(v)
                labels.append(lab)
                sources += res
        data = max_label(labels)
        if sp.action_class in ("disclose", "invite", "transfer") and destination_relations:
            dest = min((CLEARANCE.get(r, "PUBLIC") for r in destination_relations), key=label_rank)
            flow = "high_to_low" if label_rank(data) > label_rank(dest) else "ok"
        else:
            dest, flow = None, "none"
        return {"data_label": data, "label_sources": sorted(set(sources)), "destination_clearance": dest,
                "flow": flow}
