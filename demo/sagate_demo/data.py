"""Read-only access to the project's own files on main: cases, recorded gate predictions, reports, handbooks.

Nothing is copied: the demo reads the team's committed files, so it shows the numbers of the branch it is deployed
from. Every number is computed against the team's current labels (annotations/), the labels the final reports use.
Numbers that exist only in the team's final PDF reports (the final system, B4, the ablations, AgentDojo) are kept in
data/reported.json, copied from those reports.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import streamlit as st

REPO = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sagate.config import load_condition  # noqa: E402
from sagate.data.cases import Case, load_cases  # noqa: E402
from sagate.evidence.mask import EvidenceMask  # noqa: E402
from sagate.eval import metrics as M  # noqa: E402

RESULTS = REPO / "results" / "data"
SPLITS = {"test": "Test set · 212", "dev": "Dev set · 236", "attacks": "Red-team attacks · 61",
          "combos": "Combinations · 216"}
EXTRA_SPLITS = ("attacks", "combos")          # sets made after Run 1: Run 1's gates were never run on them
SPLIT_HELP = ("Test = the final exam, scored once at the end. Dev = used for tuning. Red-team = 61 cases written to "
              "try to break the gate. Combinations = 216 generated cases that mix risk factors in pairs the training "
              "data never had, labelled by the team's rule program.")
CASE_FILES = {"test": "test_cases.jsonl", "dev": "dev_cases.jsonl", "attacks": "attack_cases.jsonl",
              "combos": "dev_combos.jsonl"}

# Where each recorded gate's predictions live on main, newest run first: the first file that exists is used.
# {pool} is test / dev / attacks / combos; {n} is "" or "_noisy" (patterns without {n} have no noisy run).
_RUN1 = "run1/{pool}/{cond}{n}.jsonl"
_BASELINES = "2026-11-14_baselines_b1b3/{pool}/{cond}{n}.jsonl"           # final re-run of B1-B3 (if committed)
SOURCES = {
    "b1_rules": [_BASELINES, _RUN1],
    "b2_prompt_binary": [_BASELINES, _RUN1],
    "b3_prompt_4way": [_BASELINES, _RUN1],
    "b5_qlora_4way": [_RUN1],
    "b5_guarded": [_RUN1],
    "b5_inferred_prov": [_RUN1],
    "b5_v2_gateexp": ["2026-11-12_gateexp_tags_ab_b5v2/tags/{pool}/{cond}{n}.jsonl"],
    "b5_v3_combo_gateexp": ["2026-11-12_replay_review_fixes/{cond}.{pool}.new.jsonl"],
    # the final model alone and the final system: used as soon as the team commits these folders
    "b5_v4_combo": ["2026-11-13_eval_v4/{pool}/{cond}{n}.jsonl"],
    "b5_v4_combo_gateexp": ["2026-11-13_gateexp_b5v4combo_final/{pool}/{cond}{n}.jsonl"],
}
# the team's own reports for the GateExp versions (they count policy confirmations separately)
TEAM_REPORTS = {"b5_v2_gateexp": "2026-11-12_gateexp_tags_ab_b5v2/tags/{pool}/{cond}.report.json",
                "b5_v3_combo_gateexp": "2026-11-12_replay_review_fixes/{cond}.{pool}.new.report.json",
                "b5_v4_combo_gateexp": "2026-11-13_gateexp_b5v4combo_final/{pool}/{cond}.report.json"}


def _path(cond: str, split: str, noisy: bool = False) -> Path | None:
    for pat in SOURCES.get(cond, []):
        if noisy and "{n}" not in pat:
            continue
        p = RESULTS / pat.format(pool=split, cond=cond, n="_noisy" if noisy else "")
        if p.exists():
            return p
    return None


def source_of(cond: str, split: str) -> str:
    """Which recorded run a gate's predictions on this set come from (the results folder name)."""
    p = _path(cond, split)
    return p.relative_to(RESULTS).parts[0] if p else ""


@st.cache_resource(show_spinner=False)
def cases(split: str) -> dict[str, Case]:
    return {c.case_id: c for c in load_cases(REPO / "annotations" / CASE_FILES[split])}


@st.cache_resource(show_spinner=False)
def train_cases() -> dict[str, Case]:
    """The training split (only used for dataset statistics; never shown as a scored case)."""
    return {c.case_id: c for c in load_cases(REPO / "annotations" / "train_human.jsonl")}


@st.cache_resource(show_spinner=False)
def predictions(split: str, cond: str, noisy: bool = False) -> dict[str, dict] | None:
    p = _path(cond, split, noisy)
    if p is None:
        return None
    with open(p) as f:
        return {r["case_id"]: r for r in map(json.loads, f)}


@st.cache_data(show_spinner=False)
def reports(split: str) -> dict[str, dict]:
    """Every recorded gate scored here, the same way, against the team's current labels."""
    out: dict[str, dict] = {}
    for cond in SOURCES:
        for noisy in (False, True):
            preds = predictions(split, cond, noisy)
            if preds is not None:
                out[cond + ("_noisy" if noisy else "")] = {
                    k: (str(v) if not isinstance(v, (int, float, dict)) else v)
                    for k, v in M.compute(preds.values(), cases(split).values()).items()}
    return out


@st.cache_data(show_spinner=False)
def team_report(cond: str, split: str) -> dict:
    """The team's own report for a GateExp version (confirmations counted separately)."""
    pat = TEAM_REPORTS.get(cond)
    p = RESULTS / pat.format(pool=split, cond=cond) if pat else None
    if not p or not p.exists():
        return {}
    r = json.loads(p.read_text())
    return r.get(cond) if isinstance(r.get(cond), dict) else r


@st.cache_data(show_spinner=False)
def reported() -> dict:
    """The team's final numbers, copied from results/final/*.pdf (see the file's _source)."""
    return json.loads((DEMO / "data" / "reported.json").read_text())


def official(model: str, split: str = "test") -> dict:
    return (reported()["pools"].get(split) or {}).get(model) or {}


@st.cache_resource(show_spinner=False)
def gate_view(split: str, case_id: str):
    """The GateInput exactly as the trained gates see it (known provenance, all evidence, retrieved clauses)."""
    c = cases(split)[case_id]
    return EvidenceMask.from_condition(load_condition("b5_qlora_4way")).apply(c.input, c.alt_provenance)


@st.cache_data(show_spinner=False)
def handbook() -> dict[str, dict]:
    """Every clause of both handbooks: id -> {title, text}."""
    out: dict[str, dict] = {}
    for f in (REPO / "resources" / "handbooks").glob("*.md"):
        cur = None
        for line in f.read_text().splitlines():
            m = re.match(r"^###\s*\[([A-Z]+-\d+\.\d+)\]\s*(.*)$", line)
            if m:
                cur = m.group(1)
                out[cur] = {"title": m.group(2).strip(), "text": ""}
            elif line.startswith("#"):
                cur = None
            elif cur:
                out[cur]["text"] = (out[cur]["text"] + " " + line.strip()).strip()
    return out


@st.cache_data(show_spinner=False)
def featured() -> list[dict]:
    import yaml

    return yaml.safe_load((DEMO / "featured.yaml").read_text())["scenarios"]


@st.cache_data(show_spinner=False)
def asset(name: str) -> str:
    return (DEMO / "assets" / name).read_text()


def rate(s) -> tuple[int, int, float] | None:
    """'186/212 (87.7%)' -> (186, 212, 87.7)."""
    m = re.match(r"\s*(\d+)/(\d+)", str(s or ""))
    if not m:
        return None
    n, d = int(m.group(1)), int(m.group(2))
    return n, d, (100.0 * n / d if d else float("nan"))
