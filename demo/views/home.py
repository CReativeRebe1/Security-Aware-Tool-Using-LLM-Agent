import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X

C.hero("CL3410 course project · Run 1 results",
       "SA-Gate: a security gate for AI assistants",
       "AI assistants can now send emails, share files and move money. SA-Gate checks every risky action before "
       "it happens. It allows it, blocks it, asks the user, or asks a manager.", art="hero.svg")

a, b, c, _ = st.columns([1.15, 1.15, 1, 1.2])
if a.button("Try the Gate Lab", icon=":material/science:", type="primary", width="stretch"):
    st.switch_page("views/lab.py")
if b.button("Watch real cases", icon=":material/play_circle:", width="stretch"):
    st.switch_page("views/playground.py")
if c.button("See the results", icon=":material/monitoring:", width="stretch"):
    st.switch_page("views/results.py")

C.numbers([("1,497", "cases labelled by the team"), ("142", "scenario families"),
           ("2", "worlds: office and bank"), ("15", "risky tools checked"), ("48", "written policy rules"),
           ("6", "gate designs compared (B0–B5)")])
st.write("")
C.section("The problem")
st.markdown("### Three ways an assistant can go wrong")
C.cards([
    {"kicker": "🤖 It can act", "title": "Actions are real",
     "body": "The assistant doesn't just answer. It sends emails, deletes files and pays bills. A mistake "
             "can't be taken back."},
    {"kicker": "📧 It can be tricked", "title": "Content can give orders",
     "body": "An email or a bill can hide an instruction (a “prompt injection”). The assistant may obey it as if "
             "the user had said it."},
    {"kicker": "🪪 It can overstep", "title": "Some actions need permission",
     "body": "Even when the user asks, a big payment may need the manager, and secret data must never leave."},
])

C.section("Our idea")
st.markdown("### A gate in front of every risky action")
st.graphviz_chart("""
digraph {
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; node [shape=box style="rounded,filled" fontname="Helvetica"
  fontsize=11 color="#d8d7d2" fillcolor="#ffffff" fontcolor="#0b0b0b" margin="0.18,0.08"];
  edge [color="#9a9993" fontname="Helvetica" fontsize=10 fontcolor="#52514e"];
  user [label="User request"]; agent [label="AI agent"];
  ev [label="Evidence\\nwhere it came from · who may approve\\nhow secret · which rules apply"];
  gate [label="SA-Gate" fillcolor="#2a78d6" fontcolor="white" color="#2a78d6" fontsize=13];
  tool [label="Action runs" fillcolor="#e6f4ec" color="#bfe3cd"]; stop [label="Refused" fillcolor="#fdeceb" color="#f6c7c3"];
  ask [label="Ask the user" fillcolor="#eef4fd" color="#c9dcf6"]; esc [label="Ask the manager" fillcolor="#fdf1dc" color="#f2d49b"];
  user -> agent; agent -> gate [label=" wants to act"]; ev -> gate;
  gate -> tool [label="ALLOW"]; gate -> stop [label="BLOCK"]; gate -> ask [label="ASK_USER"]; gate -> esc [label="ESCALATE"];
  ask -> gate [style=dashed label="answer"]; esc -> gate [style=dashed label="answer"];
}
""")

st.markdown("### Four decisions, not just yes or no")
C.cards([{"kicker": C.chip(d), "title": X.DECISION_PLAIN[d], "body": "Example: " + X.DECISION_EXAMPLE[d]}
         for d in X.DECISIONS], four=True)
st.caption("A yes/no gate has to either take the risk or refuse. Asking the user, or the manager, lets the gate be "
           "safe **and** useful when something is missing.")

C.section("Results so far")
st.markdown("### Our trained gate (B5) on the test set")
rep = D.reports("test")
b5, b3 = rep.get("b5_qlora_4way", {}), rep.get("b3_prompt_4way", {})


def tile(key, label, target_pct=None):
    r5, r3 = D.rate(b5.get(key)), D.rate(b3.get(key))
    if not r5:
        return ""
    target = None
    if target_pct is not None:
        target = ("ok", f"✓ meets the target (≤ {target_pct}%)") if r5[2] <= target_pct else \
                 ("bad", f"✕ target is ≤ {target_pct}%: not there yet")
    note = f"Untrained AI (B3): {r3[2]:.1f}%" if r3 else ""
    return C.stat_tile(label, f"{r5[2]:.1f}%", f"{r5[0]}/{r5[1]}", target, note)


C.show('<div class="sg-grid">' + tile("final_resolution_success", "Cases handled correctly")
       + tile("unauthorized_action_rate", "Unsafe actions let through", 5)
       + tile("unnecessary_deferral_rate", "Questions nobody needed", 10) + "</div>")
st.markdown("Training clearly helps: B5 beats the same AI used with instructions only (B3) on every measure, and "
            "it almost never asks a needless question. But it still lets **too many unsafe actions through**, so "
            "the work continues.")
st.page_link("views/results.py", label="See all numbers and honest caveats", icon=":material/arrow_forward:")

C.section("Explore the site")
st.markdown("### Where to go next")
GUIDE = [
    ("views/lab.py", ":material/science:", "Gate Lab",
     "Design a payment yourself (amount, payee, a hidden attack, a fake approval) and watch the real pipeline "
     "decide, live."),
    ("views/playground.py", ":material/play_circle:", "Playground",
     "Seven real test cases, step by step: what the user asked, what the agent tried, the evidence, and what "
     "every gate decided."),
    ("views/explore.py", ":material/search:", "Explore all cases",
     "All 448 test and dev cases with every gate's result. Filter by kind, or show only one gate's mistakes."),
    ("views/how_it_works.py", ":material/account_tree:", "How it works",
     "The pipeline, the four kinds of evidence, RAG, the question loop and how the trained gate is made."),
    ("views/results.py", ":material/monitoring:", "Results",
     "Every number from Run 1, the safety-vs-annoyance trade-off, and the honest caveats."),
    ("views/research.py", ":material/biotech:", "The research",
     "Our hypotheses, how the dataset was built, what has been run, the project journey, and known limits."),
]
for row in range(0, len(GUIDE), 3):
    cols = st.columns(3)
    for col, (page, icon, title, text) in zip(cols, GUIDE[row:row + 3]):
        with col.container(border=True, height="stretch"):
            st.page_link(page, label=f"**{title}**", icon=icon)
            st.caption(text)
