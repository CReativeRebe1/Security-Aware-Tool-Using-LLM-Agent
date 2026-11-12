import json

import streamlit as st

from sagate_demo import components as C
from sagate_demo import explain as X
from sagate_demo import lab as L

C.page_hero("Gate Lab", "Design a payment, watch the gate decide",
            "Choose who gets paid, how much, and where the request came from: typed by you, from a bill, or a "
            "hidden [[prompt injection]]. **Nothing here is pre-recorded:** the project's own evidence builder, "
            "rule retriever and rules gate run live on every change.")

DEFAULTS = {"lab_payee": "friend", "lab_amount": 200, "lab_source": "you", "lab_fake": False, "lab_answer": "Yes",
            "lab_prov": "known", "lab_guards": False}

PRESETS = {
    "📧 A hidden attack": {"lab_payee": "new", "lab_amount": 450, "lab_source": "hidden", "lab_fake": False},
    "💰 A big payment": {"lab_payee": "friend", "lab_amount": 3000, "lab_source": "you", "lab_fake": False},
    "🎭 A fake approval": {"lab_payee": "friend", "lab_amount": 3000, "lab_source": "you", "lab_fake": True},
    "🧾 Paying a bill": {"lab_payee": "new", "lab_amount": 200, "lab_source": "bill", "lab_fake": False},
    "🔢 A one-digit typo": {"lab_payee": "typo", "lab_amount": 200, "lab_source": "you", "lab_fake": False},
}


def apply(preset):
    st.session_state.update(PRESETS[preset])      # every preset sets payee, amount, source and the note


st.markdown("**Start from an example, or set everything yourself:**")
cols = st.columns(len(PRESETS))
for col, name in zip(cols, PRESETS):
    col.button(name, on_click=apply, args=(name,), width="stretch")

left, right = st.columns([1, 1.55], gap="large")
with left, st.container(border=True, key="glass_lab_form"):
    st.markdown("#### Your payment")
    st.radio("Who gets the money?", list(L.PAYEES), key="lab_payee", index=0,
             format_func=lambda k: L.PAYEES[k][1], captions=[f"IBAN {L.PAYEES[k][0]}" for k in L.PAYEES])
    st.session_state.setdefault("lab_amount", DEFAULTS["lab_amount"])
    st.select_slider("How much?", options=L.AMOUNTS, key="lab_amount", format_func=lambda a: f"{a:,}")
    st.caption("Your limits: 1,500 to a known payee, 500 to a new one. Above that the manager decides, up to "
               "5,000.")
    st.radio("Where did the payment come from?", list(L.SOURCES), key="lab_source", index=0,
             format_func=lambda k: L.SOURCES[k])
    st.toggle("Add a note: “the manager already approved it”", key="lab_fake", value=False,
              help="A 1.00 transfer whose description claims the manager approved this payment, as in the "
                   "authority-spoofing cases of our dataset.")
    st.segmented_control("If the gate asks you, you answer", ["Yes", "No"], key="lab_answer", default="Yes")
    with st.expander("Gate settings"):
        st.segmented_control("Provenance", ["known", "guessed"], key="lab_prov", default="known",
                             help="known = we know which text was injected (best case) · guessed = string "
                                  "matching, as a real system must")
        st.toggle("Safety guards", key="lab_guards", value=False)

x = L.LabInput(payee=st.session_state["lab_payee"], amount=int(st.session_state["lab_amount"]),
               source=st.session_state["lab_source"], fake_note=bool(st.session_state["lab_fake"]),
               answer_yes=(st.session_state.get("lab_answer") or "Yes") == "Yes",
               provenance={"known": "oracle", "guessed": "inferred"}[st.session_state.get("lab_prov") or "known"],
               guards=bool(st.session_state["lab_guards"]))
res = L.run(x)
final = res.trace["final_decision"]

with right:
    # ---- outcome first: the thing the visitor wants to see
    reasons = L.why(res, x)
    sent = final == "ALLOW"
    head = "💸 The payment goes through" if sent else "🛑 The payment is stopped"
    tone = "ok" if sent else "bad"
    steps = "".join(f'<li><span class="sg-dot info">{i + 1}</span><span>{C.md(r)}</span></li>'
                    for i, r in enumerate(reasons) if r)
    C.show(f'<div class="sg-card {tone}"><div class="sg-kicker">Live result · B1 rules gate</div>'
           f'<h4 style="font-size:1.25rem">{head}</h4>{C.flow(res.trace)}<ul>{steps}</ul></div>')

    st.markdown("##### What happened")
    C.user_bubble(res.convo["prompt"])
    C.agent_steps(res.gate_input)

    st.markdown("##### What the gate saw")
    C.evidence_cards(X.evidence(res.gate_input), compact=True)
    with st.expander("What the agent read (treated only as data)", icon=":material/description:"):
        C.untrusted(res.gate_input)
    with st.expander("The full gate input, as JSON", icon=":material/data_object:"):
        st.code(json.dumps(res.gate_input.to_dict(), indent=2, ensure_ascii=False)[:20000], language="json")

st.info("This page runs the **rules gate (B1)**, which needs no GPU. Our trained gate (B5) reads exactly the same "
        "evidence. Running it live needs a GPU server, which comes later.", icon=":material/info:")
