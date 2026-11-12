import pandas as pd
import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo import scenario as S
from sagate_demo.gates import GATES, recorded

C.page_hero("Explore", "Every case, every decision",
            "All test, dev and red-team cases with what each gate decided. Filter the list, then **tick a row** to "
            "open that case below, told step by step.")

SYM = {"success": "✅", "warning": "🟡", "error": "❌"}


@st.cache_data(show_spinner="Loading cases…")
def table(split: str) -> pd.DataFrame:
    conds = recorded.available(split)
    rows = []
    for cid, c in D.cases(split).items():
        row = {"case_id": cid, "Kind": X.CATEGORY_PLAIN.get(c.category, c.category),
               "Request": c.input.user.get("prompt", ""),
               "2nd round": "yes" if c.input.resolution_history else "",
               "Right answer": f"{c.gold_decision} → {c.gold_final_action}"}
        oks = []
        for k in conds:
            p = (recorded.preds(split, k) or {}).get(cid)
            if p is None:
                row[GATES[k].code] = "–"
                continue
            v = X.verdict(p, c)
            oks.append(v.ok)
            row[GATES[k].code] = SYM[v.tone]
        row["_disagree"] = len(set(oks)) > 1
        row["_wrong"] = [GATES[k].code for k in conds if row[GATES[k].code] == SYM["error"]]
        row["_gold_first"] = c.gold_decision
        rows.append(row)
    return pd.DataFrame(rows)


# row 1: which dataset (needs the full width so all three options show) and the "disagree" switch
t0, t1 = st.columns([2, 1], vertical_alignment="bottom")
st.session_state.setdefault("ex_split", "test")
split = t0.segmented_control("Dataset", list(D.SPLITS), format_func=lambda s: D.SPLITS[s],
                             key="ex_split", help=D.SPLIT_HELP) or "test"
only = t1.toggle("Only cases where the gates disagree", key="ex_dis")
df = table(split)
# row 2: the filters
f1, f2, f3, t2 = st.columns(4, vertical_alignment="bottom")
kinds = f1.multiselect("Kind of case", sorted(df["Kind"].unique()), key="ex_kind", placeholder="All kinds")
gold = f2.multiselect("Right first decision", X.DECISIONS, key="ex_gold", placeholder="Any")
q = f3.text_input("Search the request", key="ex_q", placeholder="e.g. invoice, password")
codes_all = [GATES[k].code for k in recorded.available(split)]
if st.session_state.get("ex_wrong") not in [None] + codes_all:
    st.session_state["ex_wrong"] = None
wrong = t2.selectbox("Show only the mistakes (❌) of", [None] + codes_all, key="ex_wrong",
                     format_func=lambda c: "— any gate —" if c is None else
                     f"{c} · {next(g.name for g in GATES.values() if g.code == c)}")

view = df
if kinds:
    view = view[view["Kind"].isin(kinds)]
if gold:
    view = view[view["_gold_first"].isin(gold)]
if only:
    view = view[view["_disagree"]]
if q:
    view = view[view["Request"].str.contains(q, case=False, regex=False)]
if wrong:
    view = view[view["_wrong"].map(lambda w: wrong in w)]

codes = [GATES[k].code for k in recorded.available(split)]
st.caption(f"**{len(view)}** of {len(df)} cases · ✅ correct · 🟡 right outcome but with an unneeded question, or "
           "ran without the user's confirmation · ❌ wrong · – not scored for that gate")
sel = st.dataframe(
    view.drop(columns=["_disagree", "_gold_first", "_wrong"]), hide_index=True, width="stretch", height=380,
    on_select="rerun", selection_mode="single-row", key=f"ex_table_{split}",
    column_config={
        "case_id": None,
        "Kind": st.column_config.TextColumn(width="small"),
        "Request": st.column_config.TextColumn(width="large"),
        "2nd round": st.column_config.TextColumn(width="small", help="The case starts after one question was "
                                                                    "already asked and answered."),
        "Right answer": st.column_config.TextColumn(width="small", help="First decision → final action"),
        **{c: st.column_config.TextColumn(c, width=40, help=next(g.name for g in GATES.values() if g.code == c))
           for c in codes},
    })
picked = sel.selection.rows if sel and sel.selection else []
st.divider()
if picked and picked[0] < len(view):
    S.guided(split, view.iloc[picked[0]]["case_id"])
else:
    st.info("Tick a row in the table to open that case here.", icon=":material/touch_app:")
