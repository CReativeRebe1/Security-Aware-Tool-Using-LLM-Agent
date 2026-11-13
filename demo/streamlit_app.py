"""SA-Gate demo: entry point. Run locally with `streamlit run streamlit_app.py` from this folder."""

import hashlib
from pathlib import Path

import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D

st.set_page_config(page_title="SA-Gate · security gate for AI agents", page_icon=":material/shield:",
                   layout="wide")


# Streamlit Cloud pulls new commits into the running app but keeps st.cache_data / st.cache_resource, so after an
# update it could serve the old stylesheet or old tables. Fingerprint the demo's files and clear every cache when
# they change. (Theme changes in .streamlit/config.toml still need "Reboot app".)
def _fingerprint() -> str:
    root = Path(__file__).parent
    parts = []
    for f in sorted(p for sub in ("assets", "data", "sagate_demo", "views") for p in (root / sub).rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            s = f.stat()
            parts.append(f"{f.relative_to(root)}:{s.st_mtime_ns}:{s.st_size}")
    s = (root / "featured.yaml").stat()
    parts.append(f"featured.yaml:{s.st_mtime_ns}:{s.st_size}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()


@st.cache_resource
def _deployed() -> dict:
    return {"fingerprint": None}


_fp = _fingerprint()
if _deployed()["fingerprint"] is None:
    _deployed()["fingerprint"] = _fp
elif _deployed()["fingerprint"] != _fp:
    st.cache_data.clear()
    st.cache_resource.clear()
    _deployed()["fingerprint"] = _fp

C.load_css()
C.theme_probe()       # tells our stylesheet whether the visitor picked Light or Dark (⋮ menu → Light / Dark / System)
if not st.session_state.get("_intro_shown"):      # the opening intro plays once per visit, not on every click
    st.session_state["_intro_shown"] = True
    C.splash()
st.logo(str(Path(__file__).parent / "assets" / "logo.svg"), size="large")

pages = {
    "": [st.Page("views/home.py", title="Home", icon=":material/home:", default=True)],
    "See it in action": [
        st.Page("views/playground.py", title="Playground", icon=":material/play_circle:"),
        st.Page("views/simulation.py", title="Simulation", icon=":material/sports_score:"),
        st.Page("views/lab.py", title="Gate Lab", icon=":material/science:"),
        st.Page("views/game.py", title="Be the gate", icon=":material/stadia_controller:"),
        st.Page("views/explore.py", title="Explore all cases", icon=":material/search:"),
    ],
    "Understand it": [
        st.Page("views/how_it_works.py", title="How it works", icon=":material/account_tree:"),
        st.Page("views/results.py", title="Results", icon=":material/monitoring:"),
        st.Page("views/research.py", title="The research", icon=":material/biotech:"),
    ],
}
nav = st.navigation(pages, position="top")
nav.run()
