"""Review storage and the two-reviewer rules, shared by the server and the merge script.

Storage (one file per reviewer per batch, so files from different people never conflict in git):
    data/synthetic_data/batches/annotations/<reviewer>/<batch_id>.json
    {"annotator": ..., "batch_id": ..., "votes": {case_id: vote}}

Protocol (data/synthetic_data/batches/assignments.json):
  - every batch has exactly two reviewers; nobody else can write a review for it;
  - each case comes with a suggested decision and explanation (batches/suggestions.json); a reviewer accepts it,
    edits it, or marks the case "can't label" with a reason;
  - the two reviewers work independently and never see each other's reviews;
  - a case is decided when both reviews agree on gold_decision and gold_final_action; otherwise it is disputed
    and the two reviewers settle it by revising their own reviews.
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
SUGGESTIONS_FILE = BATCHES_DIR / "suggestions.json"
HANDBOOKS_DIR = ROOT / "resources" / "handbooks"
LABELS_DIR = ROOT / "data" / "synthetic_data" / "labels"

DECISIONS = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
FINAL_ACTIONS = ("ALLOW", "BLOCK")
MISSING_EVIDENCE = ("none", "user_intent", "recipient_identity", "resource_target", "approval",
                    "data_classification")
REQUIRED_AUTHORITY = ("none", "current_user", "resource_owner", "manager", "security_admin")
REVIEW_STATUS = ("accepted", "edited", "cannot_label")
CANNOT_LABEL_REASONS = ("unclear_request", "evidence_missing", "evidence_conflict", "no_option_fits",
                        "not_security_case", "bad_case", "other")
MATCH_FIELDS = ("gold_decision", "gold_final_action")
AGREEMENT_FIELDS = ("gold_decision", "gold_final_action", "gold_missing_evidence", "gold_required_authority")
REVIEWERS_PER_BATCH = 2


class LabelError(ValueError):
    pass


# --- assignments -------------------------------------------------------------------------------------------

def load_assignments() -> dict:
    with open(ASSIGNMENTS_FILE, encoding="utf-8") as f:
        a = json.load(f)
    for bid, b in a["batches"].items():
        r = b.get("reviewers", [])
        if len(r) != REVIEWERS_PER_BATCH or len(set(r)) != REVIEWERS_PER_BATCH:
            raise LabelError(f"{bid} must have exactly {REVIEWERS_PER_BATCH} different reviewers, has {r}")
    return a


def is_reviewer(assignments: dict, annotator: str, batch_id: str) -> bool:
    return annotator in (assignments["batches"].get(batch_id) or {}).get("reviewers", [])


def load_suggestions() -> dict:
    if not SUGGESTIONS_FILE.exists():
        return {}
    with open(SUGGESTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


# --- votes -------------------------------------------------------------------------------------------------

def validate(vote: dict) -> dict:
    """Check vocabulary and consistency."""
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
    rv = vote.get("review")
    if rv is not None:
        if not isinstance(rv, dict) or rv.get("status") not in REVIEW_STATUS:
            raise LabelError(f"review.status must be one of {REVIEW_STATUS}")
        if rv["status"] == "cannot_label":
            if rv.get("reason") not in CANNOT_LABEL_REASONS:
                raise LabelError(f"a can't-label review needs a reason from {CANNOT_LABEL_REASONS}")
            if not (rv.get("note") or "").strip():
                raise LabelError("a can't-label review needs a note")
        elif not (rv.get("explanation") or "").strip():
            raise LabelError("an accepted or edited review needs an explanation")
    return vote


def cannot_label(vote: dict | None) -> bool:
    return bool(vote) and (vote.get("review") or {}).get("status") == "cannot_label"


def is_complete(vote: dict | None) -> bool:
    """A full decision (accepted or edited review)."""
    if not vote or cannot_label(vote):
        return False
    if not all(vote.get(f) for f in AGREEMENT_FIELDS):
        return False
    if vote["gold_decision"] == "ASK_USER":
        ur = vote.get("user_response") or {}
        return bool((ur.get("text") or "").strip()) and ur.get("confirmed") in (True, False)
    return True


def is_reviewed(vote: dict | None) -> bool:
    """Counts towards a reviewer's progress: a full decision or a can't-label with its reason."""
    return is_complete(vote) or cannot_label(vote)


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


def write_vote(annotator: str, batch_id: str, case_id: str, vote: dict | None) -> dict:
    """Insert, update or (vote=None) delete one review. Read-modify-write under a per-file lock, then an atomic
    replace, so concurrent saves of different cases never lose each other's changes."""
    p = vote_file(annotator, batch_id)
    with _lock(p):
        votes = read_votes(annotator, batch_id)
        if vote is None:
            votes.pop(case_id, None)
        else:
            votes[case_id] = {**validate(vote), "case_id": case_id, "annotator": annotator,
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


# --- gold ------------------------------------------------------------------------------------------------------

def resolve(a: dict | None, b: dict | None) -> tuple[str, dict | None]:
    """(status, gold) for one case from its two reviews.

    status: unlabeled | partial | agreed | disputed | cannot_label
      partial       only one reviewer has reviewed it so far
      agreed        both made the same decision and final action -> gold
      disputed      they differ (or one labelled it and the other could not) -> the two settle it
      cannot_label  both said the case cannot be labelled -> fix or drop the case
    For an agreed case the other fields take the shared value, or the first reviewer's when they differ (those
    differences still count in the agreement statistics)."""
    done = [v for v in (a, b) if is_reviewed(v)]
    if not done:
        return ("unlabeled" if not (a or b) else "partial"), None
    if len(done) < 2:
        return "partial", None
    if cannot_label(a) and cannot_label(b):
        return "cannot_label", None
    if cannot_label(a) or cannot_label(b) or any(a[f] != b[f] for f in MATCH_FIELDS):
        return "disputed", None
    cited = Counter(c for v in (a, b) for c in v.get("gold_clause_ids") or [])
    gold = {
        "gold_decision": a["gold_decision"],
        "gold_final_action": a["gold_final_action"],
        "gold_missing_evidence": a["gold_missing_evidence"],
        "gold_required_authority": a["gold_required_authority"],
        "gold_clause_ids": sorted(cited),
        "user_response": a.get("user_response") or b.get("user_response"),
        "explanation": (a.get("review") or {}).get("explanation") or a.get("notes", ""),
        "annotators": [a["annotator"], b["annotator"]],
    }
    return "agreed", gold


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
