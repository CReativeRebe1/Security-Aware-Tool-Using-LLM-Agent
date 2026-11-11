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

RUN_DIR = REPO / "results" / "data" / "run1"
SPLITS = {"test": "Test set · 212 cases", "dev": "Dev set · 236 cases"}
SPLIT_HELP = "Test = the final exam (never used to make design choices). Dev = used for tuning."
CODE_HASH = "da42a96"


@st.cache_resource(show_spinner=False)
def cases(split: str) -> dict[str, Case]:
    return {c.case_id: c for c in load_cases(REPO / "annotations" / f"{split}_cases.jsonl")}


@st.cache_resource(show_spinner=False)
def predictions(split: str, cond: str, noisy: bool = False) -> dict[str, dict] | None:
    path = RUN_DIR / split / f"{cond}{'_noisy' if noisy else ''}.jsonl"
    if not path.exists():
        return None
    with open(path) as f:
        return {r["case_id"]: r for r in map(json.loads, f)}


@st.cache_data(show_spinner=False)
def reports(split: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in ("report.json", "report_nb04_b5.json"):
        p = RUN_DIR / split / name
        if p.exists():
            out.update(json.loads(p.read_text()))
    return out


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
