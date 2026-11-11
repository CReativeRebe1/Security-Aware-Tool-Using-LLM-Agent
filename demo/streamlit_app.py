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
    "": [
        st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
        st.Page("views/playground.py", title="Playground", icon=":material/play_circle:"),
        st.Page("views/explore.py", title="Explore all cases", icon=":material/search:"),
        st.Page("views/results.py", title="Results", icon=":material/monitoring:"),
        st.Page("views/how_it_works.py", title="How it works", icon=":material/account_tree:"),
    ]
}
nav = st.navigation(pages)

with st.sidebar:
    st.caption(f"**Run 1** results · code `{D.CODE_HASH}`  \n"
               "Provisional: B4 is not trained yet and the code is still under review.")
    st.caption("CL3410 course project  \nPrabhash Padhan · Rinkesh Verma  \nShubham Kumar Sunny · Yogendra Patel")

nav.run()
