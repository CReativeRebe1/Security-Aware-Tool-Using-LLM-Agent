"""SA-Gate demo: entry point. Run locally with `streamlit run streamlit_app.py` from this folder."""

from pathlib import Path

import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D

st.set_page_config(page_title="SA-Gate · security gate for AI agents", page_icon=":material/shield:",
                   layout="wide")
C.load_css()
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
nav = st.navigation(pages)

with st.sidebar:
    src, fin = D.gateexp_source(), D.final_source()
    st.caption(f"**Results shown**  \nRun 1 · code `{D.CODE_HASH}` (10–11 Nov)  \n"
               f"GateExp · commit `{src.get('commit', '?')}` (12 Nov)  \n"
               f"Final design · commit `{fin.get('run_commit', '?')}` (12 Nov)")
    st.caption("All scored against the same labels. Next: B4 and the ablations, trained 13 Nov, get scored; the "
               "final design takes the test set once.")
    st.caption("CL3410 course project  \nPrabhash Padhan · Rinkesh Verma  \nShubham Kumar Sunny · Yogendra Patel")

nav.run()
