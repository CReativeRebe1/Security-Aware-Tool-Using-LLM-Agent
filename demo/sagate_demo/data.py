"""Read-only access to the project's real files: frozen cases, recorded gate predictions, reports, handbooks.

Nothing is exported or copied: the demo reads the files the team commits, so it always shows the numbers on the
branch it is deployed from.
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

RUN_DIR = REPO / "results" / "data" / "run1"
GX_DIR = DEMO / "data" / "gateexp"            # copied by tools/sync_gateexp.py from the GateExp branch
GX = "b5_v2_gateexp"
FINAL_DIR = DEMO / "data" / "final"           # copied by tools/sync_final.py from main
FINAL = "b5_v3_combo_gateexp"
RECORDED_DIRS = {GX: GX_DIR, FINAL: FINAL_DIR}
SPLITS = {"test": "Test set · 212", "dev": "Dev set · 236", "attacks": "Red-team attacks · 61",
          "combos": "Combinations · 216"}
EXTRA_SPLITS = ("attacks", "combos")          # sets made after Run 1: Run 1's gates were never run on them
SPLIT_HELP = ("Test = the final exam (never used to make design choices). Dev = used for tuning. Red-team = 61 cases "
              "written to try to break the gate. Combinations = 216 generated cases that mix risk factors in pairs "
              "the training data never had, labelled by the team's rule program.")
CODE_HASH = "da42a96"


@st.cache_resource(show_spinner=False)
def cases(split: str) -> dict[str, Case]:
    path = {"attacks": GX_DIR / "attack_cases.jsonl", "combos": FINAL_DIR / "combo_cases.jsonl"}.get(
        split, REPO / "annotations" / f"{split}_cases.jsonl")
    return {c.case_id: c for c in load_cases(path)}


@st.cache_resource(show_spinner=False)
def train_cases() -> dict[str, Case]:
    """The frozen training split (only used for dataset statistics; never shown as a scored case)."""
    return {c.case_id: c for c in load_cases(REPO / "annotations" / "train_human.jsonl")}


@st.cache_resource(show_spinner=False)
def predictions(split: str, cond: str, noisy: bool = False) -> dict[str, dict] | None:
    """Recorded predictions: Run 1 files, or the GateExp / final-gate runs copied into demo/data/."""
    if cond in RECORDED_DIRS:
        path = RECORDED_DIRS[cond] / split / f"{cond}{'_noisy' if noisy else ''}.jsonl"
    else:
        path = RUN_DIR / split / f"{cond}{'_noisy' if noisy else ''}.jsonl"
    if not path.exists():
        return None
    with open(path) as f:
        return {r["case_id"]: r for r in map(json.loads, f)}


@st.cache_data(show_spinner=False)
def reports(split: str) -> dict[str, dict]:
    """Run 1 reports as committed, plus GateExp and the final gate scored here against the same labels."""
    out: dict[str, dict] = {}
    for name in ("report.json", "report_nb04_b5.json"):
        p = RUN_DIR / split / name
        if p.exists():
            out.update(json.loads(p.read_text()))
    for cond in RECORDED_DIRS:
        preds = predictions(split, cond)
        if preds is not None:
            out[cond] = {k: (str(v) if not isinstance(v, (int, float, dict)) else v)
                         for k, v in M.compute(preds.values(), cases(split).values()).items()}
    return out


@st.cache_data(show_spinner=False)
def team_report(cond: str, split: str) -> dict:
    """The team's own report for GateExp or the final gate (their labels; confirmations counted separately)."""
    if cond not in RECORDED_DIRS:
        return {}
    p = RECORDED_DIRS[cond] / split / f"{cond}.report.json"
    if not p.exists():
        return {}
    r = json.loads(p.read_text())
    return r.get(cond, r) if isinstance(r.get(cond), dict) else r


def gateexp_report(split: str) -> dict:
    return team_report(GX, split)


@st.cache_data(show_spinner=False)
def gateexp_source() -> dict:
    p = GX_DIR / "SOURCE.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def final_relabels() -> dict[str, dict]:
    """case_id -> {field: [frozen label, label used for the final gate]} on dev."""
    p = FINAL_DIR / "relabels.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def final_source() -> dict:
    p = FINAL_DIR / "SOURCE.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def e2e() -> dict:
    """Live AgentDojo runs: B0 (no gate) and the final gate, 142 test scenarios (120 attacked)."""
    p = FINAL_DIR / "e2e.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def training_runs() -> dict:
    """Final training runs A-D (13 Nov): which models each run trained, from their train summaries."""
    p = FINAL_DIR / "training_runs.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def relabels() -> dict[str, dict]:
    """case_id -> {field: [frozen label, GateExp label]} for the cases GateExp relabelled."""
    p = GX_DIR / "relabels.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_resource(show_spinner=False)
def gate_view(split: str, case_id: str):
    """The GateInput exactly as B1/B5 see it (oracle provenance, all evidence, 8 retrieved clauses, checks)."""
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
