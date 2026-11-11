import streamlit as st

from sagate_demo import data as D
from sagate_demo import scenario as S

st.title("Playground")
st.markdown("Seven real cases from the test set, each showing one idea. Pick one, then go through it step by step.")

scen = D.featured()
by_short = {s["short"]: s for s in scen}
choice = st.pills("Choose a scenario", list(by_short), default=scen[0]["short"], key="pg_choice",
                  format_func=lambda s: f"{by_short[s]['icon']} {s}")
mode = st.segmented_control("View", ["Step by step", "All on one page"], default="Step by step", key="pg_mode",
                            label_visibility="collapsed")
meta = by_short.get(choice or scen[0]["short"], scen[0])

st.divider()
if mode == "All on one page":
    S.full("test", meta["id"], meta)
else:
    S.guided("test", meta["id"], meta)
