import math

import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import simulation as S
from sagate_demo.gates import FINAL, GATES, V1, recorded, reports

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
default = [k for k in ("b1_rules", "b3_prompt_4way", V1, "b5_v2_gateexp", "b5_v3_combo_gateexp", FINAL)
           if k in avail]
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
if V1 in keys:
    cards.append({"kicker": "v1 · first trained gate", "status": "info", "title": "Mostly blue, a few red",
                  "body": f"Training fixed the over-asking ({r(V1, 'unnecessary_deferral_rate')} needless), but "
                          f"{r(V1, 'unauthorized_action_rate')} of risky actions still slip through."})
for k in ("b5_v2_gateexp", "b5_v3_combo_gateexp"):
    if k in keys:
        cards.append({"kicker": f"{GATES[k].code} · {GATES[k].name}", "status": "ok", "title": "Almost no red, more yellow “?”",
                      "body": f"The [[GateExp]] rule layers let {r(k, 'unauthorized_action_rate')} unsafe actions "
                              f"through, and pay with questions ({r(k, 'unnecessary_deferral_rate')} counted as needless "
                              "here; many are deliberate [[confirmation|confirmations]])."})
if FINAL in keys:
    cards.append({"kicker": "Final system", "status": "ok", "title": "No red at all",
                  "body": f"The [[final system]] lets {r(FINAL, 'unauthorized_action_rate')} unsafe actions through "
                          f"here, with {r(FINAL, 'unnecessary_deferral_rate')} of questions counted as needless."})
else:
    off = D.official("final", split)
    if off:
        cards.append({"kicker": "Final system", "status": "info", "title": "Not in this race yet",
                      "body": f"In the team's final report the [[final system]] gets {off['final_resolution_success']} "
                              f"right on this set with {off['unauthorized_action_rate']} unsafe. Its case-by-case "
                              "file is not in the repository yet, so it cannot race here."})
if cards:
    C.cards(cards, two=len(cards) <= 2)
C.note("Every square is a recorded decision from the team's runs (B1-B3 and v1 from Run 1, v2 and v3 from GateExp), "
       "scored against the same labels for every gate. On the red-team and combination sets, B1 is computed live on "
       "this server.")
