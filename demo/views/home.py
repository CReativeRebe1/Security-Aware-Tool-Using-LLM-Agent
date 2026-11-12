import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo.gates import NEWEST, OURS, reports

C.hero("CL3410 course project · updated 12 Nov",
       "SA-Gate: a security gate for AI assistants",
       "AI assistants can now send emails, share files and move money. SA-Gate checks every risky action before "
       "it happens. It allows it, blocks it, asks the user, or asks a manager.", art="hero.svg")

a, b, c, _ = st.columns([1.25, 1.1, 1.1, 0.9])
if a.button("Watch the gates race", icon=":material/sports_score:", type="primary", width="stretch"):
    st.switch_page("views/simulation.py")
if b.button("Try the Gate Lab", icon=":material/science:", width="stretch"):
    st.switch_page("views/lab.py")
if c.button("Play: be the gate", icon=":material/stadia_controller:", width="stretch"):
    st.switch_page("views/game.py")

C.numbers([("1,497", "real cases labelled by the team"), ("61", "red-team attacks"), ("142", "scenario families"),
           ("15", "risky tools checked"), ("48", "written policy rules"), ("7", "gates compared on the same cases")])

rep = reports("test")


def pct(k, key):
    r = D.rate((rep.get(k) or {}).get(key))
    return r[2] if r else None


C.section("The problem")
st.markdown("### Three ways an assistant can go wrong")
C.cards([
    {"kicker": "Risk 1", "title": '<span class="sg-icon">🤖</span>It can act',
     "body": "The assistant doesn't just answer. It sends emails, deletes files and pays bills. A mistake can't be "
             "taken back."},
    {"kicker": "Risk 2", "title": '<span class="sg-icon">📧</span>It can be tricked',
     "body": "An email or a bill can hide an instruction, a [[prompt injection]]. The assistant may obey it as if "
             "the user had said it."},
    {"kicker": "Risk 3", "title": '<span class="sg-icon">🪪</span>It can overstep',
     "body": "Even when the user asks, a big payment may need the manager, and secret data must never leave."},
])

C.section("Our idea")
st.markdown("### A gate in front of every risky action")
st.graphviz_chart("""
digraph {
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; node [shape=box style="rounded,filled" fontname="Helvetica"
  fontsize=11 color="#d6dbe4" fillcolor="#ffffff" fontcolor="#0f172a" margin="0.18,0.08"];
  edge [color="#94a3b8" fontname="Helvetica" fontsize=10 fontcolor="#475569"];
  user [label="User request"]; agent [label="AI agent"];
  ev [label="Evidence\\nwhere it came from · who may approve\\nhow secret · which rules apply"];
  gate [label="SA-Gate" fillcolor="#2a78d6" fontcolor="white" color="#2a78d6" fontsize=13];
  tool [label="Action runs" fillcolor="#e5f5ec" color="#bfe5cf"]; stop [label="Refused" fillcolor="#fdecea" color="#f6c7c3"];
  ask [label="Ask the user" fillcolor="#eaf2fd" color="#c6dbf6"]; esc [label="Ask the manager" fillcolor="#fdf2dc" color="#f2d49b"];
  user -> agent; agent -> gate [label=" wants to act"]; ev -> gate;
  gate -> tool [label="ALLOW"]; gate -> stop [label="BLOCK"]; gate -> ask [label="ASK_USER"]; gate -> esc [label="ESCALATE"];
  ask -> gate [style=dashed label="answer"]; esc -> gate [style=dashed label="answer"];
}
""")
C.lead("Reading is harmless, so it passes. Every action that **changes something** stops at the gate. The gate "
       "gets four kinds of facts: [[provenance]], [[authority]], [[sensitivity]] and the relevant handbook rules "
       "([[RAG]]). Then it picks one of **four decisions**:")
C.cards([{"kicker": C.chip(d), "title": X.DECISION_PLAIN[d], "body": "Example: " + X.DECISION_EXAMPLE[d]}
         for d in X.DECISIONS], four=True)
C.note("A yes/no gate must either take the risk or refuse. Asking the user, or the manager, lets the gate be safe "
       "**and** useful when something is missing.")

C.section("Progress so far")
st.markdown("### Unsafe actions let through, on the test set")
steps = [("b3_prompt_4way", "Step 1 · Untrained AI (B3)", "The model with instructions only. It also asks about "
                                                        "half of the cases needlessly."),
         (OURS, "Step 2 · Trained gate (B5, Run 1)", "Fine-tuned on our labels. Needless questions almost gone, but "
                                                    "still too many unsafe actions."),
         (NEWEST, "Step 3 · Newest design (GateExp)", "B5 v2 inside hard rules and checks. Unsafe actions gone on "
                                                     "test; more confirmation questions.")]
tiles = []
for k, title, text in steps:
    u, q = pct(k, "unauthorized_action_rate"), pct(k, "unnecessary_deferral_rate")
    if u is None:
        continue
    tiles.append(C.stat_tile(title, f"{u:.1f}%", "unsafe",
                             ("ok", "✓ within the 5% target") if u <= 5 else ("bad", "✕ target is ≤ 5%"),
                             f"{text} Needless questions: {q:.1f}%."))
C.show('<div class="sg-grid">' + "".join(tiles) + "</div>")
C.callout("new", "Read this honestly:",
          "some GateExp rules were written after looking at test failures, so test flatters it. On the dev set, which "
          f"nobody tuned on, it lets {reports('dev').get(NEWEST, {}).get('unauthorized_action_rate', '?')} unsafe "
          "actions through, and on 61 new red-team attacks 0%. The trade-off is more questions. The Results page "
          "shows both ways of counting them.")
st.page_link("views/results.py", label="See every number and the honest caveats", icon=":material/arrow_forward:")

C.section("Explore the site")
st.markdown("### Where to go next")
GUIDE = [
    ("views/playground.py", ":material/play_circle:", "Playground",
     "Seven real cases told step by step: the request, the agent's action, the evidence, and every gate's decision."),
    ("views/simulation.py", ":material/sports_score:", "Simulation",
     "Watch the gates decide hundreds of real cases side by side, live, with counters."),
    ("views/lab.py", ":material/science:", "Gate Lab",
     "Design a payment yourself (amount, payee, a hidden attack, a fake approval) and watch the pipeline decide."),
    ("views/game.py", ":material/stadia_controller:", "Be the gate",
     "Decide real cases yourself and compare your score with the AI gates."),
    ("views/explore.py", ":material/search:", "Explore all cases",
     "Every test, dev and red-team case with every gate's result. Filter, or show one gate's mistakes."),
    ("views/how_it_works.py", ":material/account_tree:", "How it works",
     "The pipeline, the evidence, RAG, the question loop, training, and the newest design's layers."),
    ("views/results.py", ":material/monitoring:", "Results",
     "Every number, the safety-vs-annoyance trade-off, and two ways of counting questions."),
    ("views/research.py", ":material/biotech:", "The research",
     "Hypotheses, how the dataset was built, experiments, the project journey, and known limits."),
]
for row in range(0, len(GUIDE), 4):
    cols = st.columns(4)
    for i, (col, (page, icon, title, text)) in enumerate(zip(cols, GUIDE[row:row + 4])):
        with col.container(border=True, height="stretch", key=f"glass_guide_{row + i}"):
            st.page_link(page, label=f"**{title}**", icon=icon)
            st.caption(text)
