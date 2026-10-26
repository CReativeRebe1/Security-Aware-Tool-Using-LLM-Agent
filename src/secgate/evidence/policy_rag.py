"""Policy handbook retrieval.

Handbooks mark each clause with a heading `### [WS-2.3] Title`; one clause = one retrievable unit. Retrieval is
Okapi BM25 over title + text (the corpus is a few dozen clauses, so no index library is needed). The query is
built from trusted fields only — the user's request, the tool, its action class and the registry's facts — so
injected text cannot steer which policy the gate sees.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^###\s*\[([A-Z]+-\d+\.\d+)\]\s*(.+?)\s*$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an and are as at be been by can for from has have if in into is it its may must no not of on
or that the their them then there these this those to was were when where which who will with without""".split())


@dataclass(frozen=True)
class Clause:
    id: str
    title: str
    text: str

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "text": self.text}


def parse_handbook(path: str | Path) -> list[Clause]:
    clauses: list[Clause] = []
    cur: tuple[str, str] | None = None
    buf: list[str] = []

    def flush():
        if cur:
            clauses.append(Clause(cur[0], cur[1], " ".join(x for x in buf if x).strip()))

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = _HEADING.match(line.strip())
        if m or line.startswith("#"):
            flush()
            cur, buf = ((m.group(1), m.group(2)) if m else None), []
        elif cur:
            buf.append(line.strip())
    flush()
    ids = [c.id for c in clauses]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate clause ids in {path}: {dup}")
    return clauses


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        q = Counter(query)
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            for t, qn in q.items():
                f = tf.get(t)
                if f:
                    s += qn * self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            out.append(s)
        return out


class PolicyRetriever:
    def __init__(self, handbook: str | Path):
        self.clauses = parse_handbook(handbook)
        self.index = BM25([tokenize(f"{c.title} {c.title} {c.text}") for c in self.clauses])

    def retrieve(self, query: str, k: int = 3) -> list[Clause]:
        s = self.index.scores(tokenize(query))
        order = sorted(range(len(s)), key=lambda i: (-s[i], i))
        return [self.clauses[i] for i in order[:k]]

    def get(self, clause_id: str) -> Clause | None:
        return next((c for c in self.clauses if c.id == clause_id), None)


_ACTION_TERMS = {
    "disclose": "send email share file recipient external disclosure",
    "invite": "calendar event invite participants",
    "delete": "delete deleting deletion target owner",
    "modify": "edit create file document",
    "transfer": "payment payee transfer amount limit standing order",
    "account_change": "password personal details account change identity",
}
_BASIS_TERMS = {
    "disclose_confidential_external": "confidential data leaving the company manager approval",
    "disclose_restricted": "restricted data never sent outside",
    "disclose_restricted_internal": "restricted data colleague security desk approval",
    "internal_data_to_unknown_recipient": "unknown external recipient confirm address",
    "share_write": "sharing permissions edit access owner approval",
    "delete_others_resource": "deleting files owned by someone else owner approval",
    "modify_readonly": "editing read-only file owner approval",
    "transfer_over_limit": "amounts above the limit relationship manager approval",
    "transfer_over_manager_max": "above the manager maximum prohibited",
    "standing_order_new_recipient": "redirecting standing orders new payee manager",
    "identity_change": "identity change name security desk",
}


def build_query(user_prompt: str, function: str, action_class: str, authority: dict | None,
                sensitivity: dict | None) -> str:
    """Retrieval query from trusted fields only (never from tool outputs or provenance)."""
    parts = [user_prompt or "", function.replace("_", " "), _ACTION_TERMS.get(action_class, "")]
    if authority:
        parts += [_BASIS_TERMS.get(b, b.replace("_", " ")) for b in authority.get("basis", [])]
        rels = {r["relation"] for r in authority.get("recipients", [])}
        parts += [{"unknown": "unknown external recipient", "new_payee": "new payee",
                   "client": "known external contacts", "personal": "known external contacts",
                   "internal": "internal recipients colleagues"}.get(r, "") for r in sorted(rels)]
    if sensitivity:
        if sensitivity.get("data_label") in ("CONFIDENTIAL", "RESTRICTED"):
            parts.append(sensitivity["data_label"].lower() + " data")
        if sensitivity.get("flow") == "high_to_low":
            parts.append("leaving the company outside")
    return " ".join(p for p in parts if p)


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    return len(set(retrieved[:k]) & set(gold)) / len(set(gold))
