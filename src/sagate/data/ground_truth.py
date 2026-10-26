"""The dataset's loose ground-truth match (README: `matches_*_ground_truth`): same function and a shared
distinctive value (string of >= 3 chars, dates ignored, substring either way); a ground-truth call without
distinctive values matches on the function alone. Reproduces the shipped flags on ~99% of rows.
Weak labels for analysis, variant seeding and the ScenarioResponder — never gold."""

from __future__ import annotations

import re

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
MIN_LEN = 3


def _strings(v) -> list[str]:
    if isinstance(v, dict):
        return [] if "__expr__" in v else [s for x in v.values() for s in _strings(x)]
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x)]
    return [v] if isinstance(v, str) else []


def distinctive(args) -> set[str]:
    return {s.strip().lower() for s in _strings(args) if len(s.strip()) >= MIN_LEN and not _DATE.match(s.strip())}


def matches_ground_truth(call: dict, task: dict | None) -> bool:
    if not task:
        return False
    mine = distinctive(call.get("args"))
    for gt in task.get("ground_truth_calls", []):
        if gt["function"] != call["function"]:
            continue
        theirs = distinctive(gt.get("args"))
        if not theirs or any(t in m or m in t for t in theirs for m in mine):
            return True
    return False
