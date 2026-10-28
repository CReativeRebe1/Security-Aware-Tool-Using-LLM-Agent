"""Policy handbook retrieval (ARCHITECTURE.md §5.4).

Handbook clauses are written as `### [BANK-3.2] Title`; one chunk per clause. Retrieval is BM25 (implemented
here: ~80 clauses, no dependency needed). The query uses trusted fields only, so injected text cannot steer it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_CLAUSE = re.compile(r"^###\s*\[([A-Z]+-\d+\.\d+)\]\s*(.+)$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("""a an and are as at be by for from has have if in into is it its may must not of on or that the
their them then there these this to was were when where which who will with without""".split())


@dataclass(frozen=True)
class Clause:
    id: str
    title: str
    text: str

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "text": self.text}


def parse_handbook(path: str | Path) -> list[Clause]:
    clauses, cur, buf = [], None, []
    for line in Path(path).read_text().splitlines():
        m = _CLAUSE.match(line.strip())
        if m or line.startswith("## "):
            if cur:
                clauses.append(Clause(cur[0], cur[1], " ".join(buf).strip()))
            cur, buf = (m.group(1), m.group(2).strip()) if m else None, []
        elif cur is not None:
            buf.append(line.strip())
    if cur:
        clauses.append(Clause(cur[0], cur[1], " ".join(buf).strip()))
    ids = [c.id for c in clauses]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"duplicate clause ids in {path}: {sorted(dup)}")
    return clauses


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avgdl = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in query:
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            out.append(s)
        return out


class PolicyRetriever:
    def __init__(self, handbook_path: str | Path):
        self.clauses = parse_handbook(handbook_path)
        self.index = BM25([tokenize(f"{c.title} {c.title} {c.text}") for c in self.clauses])

    def retrieve(self, query: str, k: int = 3) -> list[Clause]:
        s = self.index.scores(tokenize(query))
        order = sorted(range(len(s)), key=lambda i: (-s[i], i))
        return [self.clauses[i] for i in order[:k]]

    def by_id(self, cid: str) -> Clause | None:
        return next((c for c in self.clauses if c.id == cid), None)


_ACTION_WORDS = {
    "disclose": "send email share file recipients external disclosure confidential",
    "delete": "delete deleting file email owner",
    "modify": "edit create file modify",
    "invite": "calendar event invite participants",
    "transfer": "payment payee transfer amount limit",
    "account_change": "password personal details account security change",
}


def build_query(user_prompt: str, function: str, action: str, authority: dict | None,
                sensitivity: dict | None) -> str:
    """Query from trusted fields only: user prompt, tool name, action class, authority/sensitivity facts."""
    parts = [user_prompt or "", function.replace("_", " "), action, _ACTION_WORDS.get(action, "")]
    if authority:
        parts += [str(b).replace("_", " ") for b in authority.get("basis", [])]
        parts += [p.split(":", 1)[0].replace("_", " ") for p in authority.get("affected_party", [])]
        if authority.get("required_role") not in (None, "none", "current_user"):
            parts.append(str(authority["required_role"]).replace("_", " ") + " approval")
    if sensitivity and sensitivity.get("resource"):
        parts.append(str(sensitivity["resource"]).lower())
        if sensitivity.get("flow") == "high_to_low":
            parts.append("leaving the company external")
    return " ".join(parts)


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    return len(set(retrieved[:k]) & set(gold)) / len(set(gold))
