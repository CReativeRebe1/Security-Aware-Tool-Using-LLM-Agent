"""Label storage and the multi-annotator rules, shared by the server and the merge script.

Storage (one file per annotator per batch, so files from different people never conflict in git):
    data/synthetic_data/batches/annotations/<annotator>/<batch_id>.json
    {"annotator": ..., "batch_id": ..., "votes": {case_id: vote}}

Protocol (data/synthetic_data/batches/assignments.json):
  - two primary annotators label every case of a batch independently and without seeing each other's votes;
  - a case is disputed when both primary votes are complete and differ on gold_decision or gold_final_action;
  - the batch's tie-break annotator votes on disputed cases only, seeing both primary votes read-only;
  - an annotator can only write their own votes, and only in a batch (and role) they are assigned to.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCHES_DIR = ROOT / "data" / "synthetic_data" / "batches"
ANNOTATIONS_DIR = BATCHES_DIR / "annotations"
ASSIGNMENTS_FILE = BATCHES_DIR / "assignments.json"
HANDBOOKS_DIR = ROOT / "resources" / "handbooks"
LABELS_DIR = ROOT / "data" / "synthetic_data" / "labels"

DECISIONS = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
FINAL_ACTIONS = ("ALLOW", "BLOCK")
MISSING_EVIDENCE = ("none", "user_intent", "recipient_identity", "resource_target", "approval",
                    "data_classification")
REQUIRED_AUTHORITY = ("none", "current_user", "resource_owner", "manager", "security_admin")
TIE_FIELDS = ("gold_decision", "gold_final_action")
AGREEMENT_FIELDS = ("gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority")


class LabelError(ValueError):
    pass


# --- assignments -------------------------------------------------------------------------------------------

def load_assignments() -> dict:
    with open(ASSIGNMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def role_of(assignments: dict, annotator: str, batch_id: str) -> str | None:
    """primary | tiebreak | None."""
    b = assignments["batches"].get(batch_id) or {}
    if annotator in b.get("primary", []):
        return "primary"
    if annotator == b.get("tiebreak"):
        return "tiebreak"
    return None


# --- votes -------------------------------------------------------------------------------------------------

def validate(vote: dict) -> dict:
    """Check vocabulary and consistency; partial votes (still being filled in) are allowed."""
    def check(field, allowed):
        v = vote.get(field)
        if v not in (None, "") and v not in allowed:
            raise LabelError(f"{field}={v!r} is not one of {allowed}")

    check("gold_decision", DECISIONS)
    check("gold_final_action", FINAL_ACTIONS)
    check("gold_missing_evidence", MISSING_EVIDENCE)
    check("gold_required_authority", REQUIRED_AUTHORITY)
    d, f = vote.get("gold_decision"), vote.get("gold_final_action")
    if d in FINAL_ACTIONS and f and f != d:
        raise LabelError("for ALLOW / BLOCK the final action must equal the decision")
    ids = vote.get("gold_clause_ids") or []
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise LabelError("gold_clause_ids must be a list of clause ids")
    ur = vote.get("user_response")
    if ur is not None and not isinstance(ur, dict):
        raise LabelError("user_response must be an object")
    return vote


def is_complete(vote: dict | None) -> bool:
    if not vote:
        return False
    if not all(vote.get(f) for f in AGREEMENT_FIELDS):
        return False
    if vote["gold_decision"] == "ASK_USER":
        ur = vote.get("user_response") or {}
        return bool((ur.get("text") or "").strip()) and ur.get("confirmed") in (True, False)
    return True


def disagree(a: dict | None, b: dict | None) -> bool:
    return is_complete(a) and is_complete(b) and any(a[f] != b[f] for f in TIE_FIELDS)


# --- files -------------------------------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(path), threading.Lock())


def vote_file(annotator: str, batch_id: str) -> Path:
    return ANNOTATIONS_DIR / annotator / f"{batch_id}.json"


def read_votes(annotator: str, batch_id: str) -> dict:
    p = vote_file(annotator, batch_id)
    if not p.exists():
        return {}
    for _ in range(5):                      # a concurrent atomic replace can briefly block reads on Windows
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("votes", {})
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
    raise LabelError(f"could not read {p}")


def write_vote(annotator: str, batch_id: str, case_id: str, vote: dict | None, role: str) -> dict:
    """Insert, update or (vote=None) delete one vote. Read-modify-write under a per-file lock, then an atomic
    replace, so concurrent saves of different cases never lose each other's changes."""
    p = vote_file(annotator, batch_id)
    with _lock(p):
        votes = read_votes(annotator, batch_id)
        if vote is None:
            votes.pop(case_id, None)
        else:
            votes[case_id] = {**validate(vote), "case_id": case_id, "annotator": annotator, "role": role,
                              "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"annotator": annotator, "batch_id": batch_id,
                       "votes": dict(sorted(votes.items()))}, f, indent=1, ensure_ascii=False)
        for i in range(10):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if i == 9:
                    raise
                time.sleep(0.05)
    return votes


# --- batches -------------------------------------------------------------------------------------------------

def load_batch(batch_id: str) -> list[dict]:
    p = BATCHES_DIR / f"{batch_id}.json"
    if not p.exists():
        raise LabelError(f"unknown batch {batch_id}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def disputed_cases(assignments: dict, batch_id: str) -> dict[str, list[dict]]:
    """{case_id: [primary vote, primary vote]} for cases whose two complete primary votes differ."""
    a, b = assignments["batches"][batch_id]["primary"]
    va, vb = read_votes(a, batch_id), read_votes(b, batch_id)
    return {cid: [va[cid], vb[cid]] for cid in va if cid in vb and disagree(va[cid], vb[cid])}


# --- gold ------------------------------------------------------------------------------------------------------

def _majority(values: list) -> tuple[object, bool]:
    """(most common value, strictly more common than any other)."""
    counts = Counter(values).most_common()
    if not counts:
        return None, False
    top = counts[0]
    return top[0], len(counts) == 1 or top[1] > counts[1][1]


def resolve(primary: list[dict | None], tiebreak: dict | None) -> tuple[str, dict | None]:
    """(status, gold) for one case.

    status: unlabeled | partial | agreed | awaiting_tiebreak | resolved | unresolved
    Gold decision and final action come from the agreeing primaries, otherwise from the majority of all three
    votes. The other fields take the most common value among the votes that agree with the gold decision and
    final action (ties go to the tie-break vote, then to the first primary)."""
    done = [v for v in primary if is_complete(v)]
    if not done:
        return ("unlabeled" if not any(primary) else "partial"), None
    if len(done) < 2:
        return "partial", None
    if not disagree(*done):
        status, voters = "agreed", done
    elif not is_complete(tiebreak):
        return "awaiting_tiebreak", None
    else:
        voters = [*done, tiebreak]
        key, ok = _majority([tuple(v[f] for f in TIE_FIELDS) for v in voters])
        if not ok:
            return "unresolved", None
        status = "resolved"
    key = tuple(voters[0][f] for f in TIE_FIELDS) if status == "agreed" else key
    support = [v for v in voters if tuple(v[f] for f in TIE_FIELDS) == key]
    order = sorted(support, key=lambda v: v.get("role") != "tiebreak")        # tie-break vote first

    def pick(field):
        counts = Counter(v[field] for v in support).most_common()
        best = [val for val, n in counts if n == counts[0][1]]
        return next(v[field] for v in order if v[field] in best)

    cited = Counter(c for v in support for c in v.get("gold_clause_ids") or [])
    gold = {
        "gold_decision": key[0],
        "gold_final_action": key[1],
        "gold_missing_evidence": pick("gold_missing_evidence"),
        "gold_required_authority": pick("gold_required_authority"),
        "gold_clause_ids": sorted(c for c, n in cited.items() if n * 2 >= len(support)),
        "user_response": next((v.get("user_response") for v in order if v.get("user_response")), None),
        "annotators": [v["annotator"] for v in voters],
    }
    return status, gold


# --- policies --------------------------------------------------------------------------------------------------

def load_policies() -> list[dict]:
    """Clauses of every handbook in resources/handbooks/*.md, written as `### [ID] Title` + text."""
    out = []
    for path in sorted(HANDBOOKS_DIR.glob("*.md")):
        cur = None
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("### [") and "]" in s:
                cur = {"id": s[5:s.index("]")], "title": s[s.index("]") + 1:].strip(), "text": "",
                       "doc": path.stem}
                out.append(cur)
            elif s.startswith("#"):
                cur = None
            elif cur is not None and s and not s.startswith(">"):
                cur["text"] = (cur["text"] + " " + s).strip()
    return out
