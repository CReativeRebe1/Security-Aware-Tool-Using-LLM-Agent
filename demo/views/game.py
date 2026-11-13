import random

import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo.gates import GATES, newest, recorded

C.page_hero("Game", "You be the gate",
            "Read a real case from the [[test set]] and decide what the gate should do. Then see the right answer, "
            "why it is right, and what the AI gates decided. Can you beat them?")

SPLIT = "test"
RIVALS = ["b1_rules", "b5_qlora_4way", newest(SPLIT)]   # final design is held back on test
cases = D.cases(SPLIT)


def new_game():
    ids = [cid for cid, c in cases.items() if not c.input.resolution_history]   # cases that start fresh
    random.Random().shuffle(ids)
    st.session_state.update(game_ids=ids, game_i=0, game_answer=None,
                            game_score={"played": 0, "you": 0, **{k: 0 for k in RIVALS}})


if "game_ids" not in st.session_state:
    new_game()

ids = st.session_state.game_ids
cid = ids[st.session_state.game_i % len(ids)]
c = cases[cid]
gi = D.gate_view(SPLIT, cid)


def answer(choice):
    if st.session_state.game_answer is not None:
        return
    st.session_state.game_answer = choice
    sc = st.session_state.game_score
    sc["played"] += 1
    sc["you"] += choice == c.gold_decision
    for k in RIVALS:
        p = (recorded.preds(SPLIT, k) or {}).get(cid)
        sc[k] += bool(p and p["first_decision"] == c.gold_decision)


def next_case():
    st.session_state.game_i += 1
    st.session_state.game_answer = None


sc = st.session_state.game_score
cells = [("You", sc["you"])] + [(GATES[k].code, sc[k]) for k in RIVALS]
C.show('<div class="sg-game-score">' + "".join(
    f'<div class="s">{C.esc(n)}<b>{v} / {sc["played"]}</b></div>' for n, v in cells) +
    f'<div class="s">Case<b>{st.session_state.game_i + 1}</b></div></div>')
st.write("")

left, right = st.columns([1.7, 1], gap="large")
with left:
    C.show(C.tag(X.CATEGORY_PLAIN.get(c.category, c.category), "violet") + C.tag(c.input.suite))
    C.user_bubble(gi.user.get("prompt", ""))
    C.agent_steps(gi)
    st.markdown("**What the gate knows**")
    C.evidence_cards(X.evidence(gi), compact=True)
    if gi.untrusted_content:
        with st.expander("What the agent read (treated only as data)", icon=":material/description:"):
            C.untrusted(gi)

with right:
    chosen = st.session_state.game_answer
    with st.container(border=True, key="glass_game_choice"):
        st.markdown("#### What should the gate do?")
        for d in X.DECISIONS:
            st.button(f"{X.DECISION_ICON[d]}  {d}", key=f"g_{d}", on_click=answer, args=(d,), width="stretch",
                      type="primary" if chosen == d else "secondary", disabled=chosen is not None,
                      help=X.DECISION_PLAIN[d])
        st.caption("Tip: look at who asked for it, who may approve it, and whether secret data is leaving.")

    if chosen is not None:
        right_answer = c.gold_decision
        ok = chosen == right_answer
        tone = "ok" if ok else "bad"
        head = "✓ Right!" if ok else f"✕ Not quite. The right answer is {right_answer}"
        bits = []
        if c.gold_missing_evidence and c.gold_missing_evidence != "none":
            bits.append(f"What's missing: <b>{C.esc(c.gold_missing_evidence.replace('_', ' '))}</b>")
        if c.gold_required_authority and c.gold_required_authority not in ("none",):
            bits.append(f"Who decides: <b>{C.esc(X.ROLE_PLAIN.get(c.gold_required_authority))}</b>")
        bits.append(f"Final outcome: {C.chip(c.gold_final_action)}")
        C.show(f'<div class="sg-card {tone}"><h4>{C.esc(head)}</h4>'
               f'<p style="margin-bottom:8px">You chose {C.chip(chosen)} · right answer {C.chip(right_answer)}</p>'
               f'<p style="margin-top:8px">{X.DECISION_PLAIN[right_answer]}.</p>'
               f'<p style="margin-top:6px">{" · ".join(bits)}</p></div>')
        book = D.handbook()
        rules = [f"`{r}` {book.get(r, {}).get('title', '')}" for r in c.gold_clause_ids or []]
        if rules:
            C.note("Rules that apply: " + " · ".join(rules))
        st.markdown("**What the gates decided first**")
        rows = []
        for k in RIVALS:
            p = (recorded.preds(SPLIT, k) or {}).get(cid)
            if p is None:
                continue
            mark = "✓" if p["first_decision"] == right_answer else "✕"
            rows.append(f'<li><span class="sg-dot {"ok" if mark == "✓" else "bad"}">{mark}</span>'
                        f'<span><b>{C.esc(GATES[k].code)}</b> {C.esc(GATES[k].name)}: {C.chip(p["first_decision"])}'
                        f'</span></li>')
        C.show(f'<div class="sg-card"><ul style="margin:0">{"".join(rows)}</ul></div>')
        if cid in D.relabels():
            C.note("This case was relabelled on the [[GateExp]] branch (new payee or new amount = confirm). The game "
                   "uses the team's [[frozen labels]].")
        st.button("Next case →", on_click=next_case, type="primary", width="stretch")

st.divider()
if st.button("Start over with new cases", icon=":material/restart_alt:"):
    new_game()
    st.rerun()
