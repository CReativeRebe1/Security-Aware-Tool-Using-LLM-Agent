import math

import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import simulation as S
from sagate_demo.gates import GATES, NEWEST, recorded, reports

C.page_hero("Simulation", "Watch the gates race",
            "Every gate decides the **same real cases in the same order**. Each square is one case: watch where "
            "they agree, where they [[unsafe|let something unsafe through]], and where they ask "
            "[[needless question|questions nobody needed]]. Press ▶ Play.")

c1, c3 = st.columns([2.2, 1], vertical_alignment="bottom")
st.session_state.setdefault("sim_split", "test")
split = c1.segmented_control("Cases", list(D.SPLITS), key="sim_split", format_func=lambda s: D.SPLITS[s],
                             help=D.SPLIT_HELP) or "test"
order = c3.segmented_control("Order", ["shuffled", "by kind"], default="shuffled", key="sim_order") or "shuffled"
avail = recorded.available(split)
default = [k for k in ("b1_rules", "b3_prompt_4way", "b5_qlora_4way", NEWEST) if k in avail]
keys = st.pills("Gates in the race", avail, selection_mode="multi", default=default, key=f"sim_gates_{split}",
                format_func=lambda k: f"{GATES[k].code} · {GATES[k].name}") or default

data = S.payload(split, keys, order="shuffled" if order == "shuffled" else "kind")
n = len(data["cases"])
rows = math.ceil(n / 52)
# Our own generated page; every piece of case text is escaped by the page's JavaScript before display.
st.iframe(S.html_page(data, seconds=16), height=250 + len(keys) * (52 + rows * 17))

st.markdown("### What to look for")
rep = reports(split)


def r(k, key):
    v = D.rate((rep.get(k) or {}).get(key))
    return f"{v[2]:.1f}%" if v else "–"


cards = []
if "b3_prompt_4way" in keys:
    cards.append({"kicker": "B3 · untrained AI", "status": "warn", "title": "Lots of yellow “?”",
                  "body": f"Without training, the AI asks about almost everything: {r('b3_prompt_4way', 'unnecessary_deferral_rate')} "
                          "of its questions were not needed, and it still lets unsafe actions through."})
if "b2_prompt_binary" in keys:
    cards.append({"kicker": "B2 · yes/no only", "status": "warn", "title": "Lots of grey",
                  "body": f"It cannot ask, so it blocks: {r('b2_prompt_binary', 'over_blocking_rate')} of good actions "
                          "are refused. Safe-looking, but useless."})
if "b1_rules" in keys:
    cards.append({"kicker": "B1 · rules", "status": "info", "title": "Calm, but red where judgement is needed",
                  "body": f"Rules never ask needlessly, but {r('b1_rules', 'unauthorized_action_rate')} of risky actions "
                          "slip through: the cases that need judgement, not a fixed rule."})
if "b5_qlora_4way" in keys:
    u5 = D.rate((rep.get("b5_qlora_4way") or {}).get("unauthorized_action_rate"))
    verdict5 = ("still above the 5% target" if u5 and u5[2] > 5 else
                "within the 5% target here, but on the test set it was 16.9%")
    cards.append({"kicker": "B5 · trained (Run 1)", "status": "info", "title": "Mostly blue, a few red",
                  "body": f"Training fixed the over-asking ({r('b5_qlora_4way', 'unnecessary_deferral_rate')} needless). "
                          f"Unsafe: {r('b5_qlora_4way', 'unauthorized_action_rate')}, {verdict5}."})
if NEWEST in keys:
    cards.append({"kicker": "GX · newest design", "status": "ok", "title": "Almost no red, more yellow “?”",
                  "body": f"[[GateExp]] lets {r(NEWEST, 'unauthorized_action_rate')} unsafe actions through, and pays "
                          f"with questions ({r(NEWEST, 'unnecessary_deferral_rate')} counted as needless here; many are "
                          "deliberate [[confirmation|confirmations]] before payments to new payees)."})
if cards:
    C.cards(cards, two=len(cards) <= 2)
C.note("Every square is a recorded decision from the team's runs (Run 1 on 10–11 Nov, GateExp on 12 Nov), scored "
       "against the [[frozen labels]]. On the red-team set, B1 is computed live on this server.")
