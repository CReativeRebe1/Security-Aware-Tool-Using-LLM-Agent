import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo.gates import NEWEST, OURS, PREV_GX, reports

C.hero("CL3410 course project · updated 13 Nov",
       "SA-Gate: a security gate for AI assistants",
       "AI assistants can now send emails, share files and move money. SA-Gate checks every risky action before "
       "it happens. It allows it, blocks it, asks the user, or asks a manager.", art="mock", highlight="AI assistants")

a, b, c, _ = st.columns([1.25, 1.1, 1.1, 0.9])
if a.button("Watch the gates race", icon=":material/sports_score:", type="primary", width="stretch"):
    st.switch_page("views/simulation.py")
if b.button("Try the Gate Lab", icon=":material/science:", width="stretch"):
    st.switch_page("views/lab.py")
if c.button("Play: be the gate", icon=":material/stadia_controller:", width="stretch"):
    st.switch_page("views/game.py")

_live = (D.e2e().get(NEWEST) or {}).get("test/all") or {}
C.numbers([("1,497", "real cases labelled by the team"), ("61", "red-team attacks"), ("216", "combination cases"),
           ("142", "scenario families"), ("8", "gates compared"),
           (_live.get("attack_success_rate", "–").split(" ")[0], "attacks that worked in the live agent run")])


def pct(k, key, split="test"):
    r = D.rate((reports(split).get(k) or {}).get(key))
    return r[2] if r else None


C.section("The problem")
st.markdown("### Three ways an assistant can go wrong")
C.cards([
    {"kicker": "Risk 1", "title": C.icon("smart_toy", "badge") + "It can act",
     "body": "The assistant doesn't just answer. It sends emails, deletes files and pays bills. A mistake can't be "
             "taken back."},
    {"kicker": "Risk 2", "title": C.icon("mail", "badge") + "It can be tricked",
     "body": "An email or a bill can hide an instruction, a [[prompt injection]]. The assistant may obey it as if "
             "the user had said it."},
    {"kicker": "Risk 3", "title": C.icon("badge", "badge") + "It can overstep",
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
st.markdown("### Unsafe actions let through")
steps = [("b3_prompt_4way", "test", "Step 1 · Untrained AI (B3) · test",
          "The model with instructions only. It also asks about half of the cases needlessly."),
         (OURS, "test", "Step 2 · Trained gate (B5, Run 1) · test",
          "Fine-tuned on our labels. Needless questions almost gone, but still too many unsafe actions."),
         (PREV_GX, "test", "Step 3 · GateExp (GX) · test",
          "B5 v2 inside hard rules and checks. Unsafe actions gone on test; more confirmation questions."),
         (NEWEST, "dev", "Step 4 · Final design (GX3) · dev",
          "Retrained on factor combinations, plus review fixes. Test is held back for one final run.")]
tiles = []
for k, split, title, text in steps:
    u, q = pct(k, "unauthorized_action_rate", split), pct(k, "unnecessary_deferral_rate", split)
    if u is None:
        continue
    tiles.append(C.stat_tile(title, f"{u:.1f}%", "unsafe",
                             ("ok", "✓ within the 5% target") if u <= 5 else ("bad", "✕ target is ≤ 5%"),
                             f"{text} Needless questions: {q:.1f}%."))
C.show('<div class="sg-grid four">' + "".join(tiles) + "</div>")
C.callout("new", "Read this honestly:",
          "some GateExp rules were written after looking at test failures, so test flatters GX. That is why the final "
          "design (GX3) is [[held back]] from test until one final run. On sets nobody tuned on it lets "
          f"{reports('dev').get(NEWEST, {}).get('unauthorized_action_rate', '?')} unsafe actions through on dev, "
          f"{reports('attacks').get(NEWEST, {}).get('unauthorized_action_rate', '?')} on the red-team attacks and "
          f"{reports('combos').get(NEWEST, {}).get('unauthorized_action_rate', '?')} on the new combinations. "
          "The trade-off is more questions; the Results page shows both ways of counting them.")

if _live and D.e2e().get("b0"):
    st.markdown("### Inside a real agent")
    C.lead("The whole AI agent ran 142 [[AgentDojo]] tasks, 120 of them with a hidden attack, once without a gate "
           "and once with the final design in front of every risky action. Here the gate has to guess where text "
           "came from, as a real system must.")
    b0 = D.e2e()["b0"]
    a0, a1 = D.rate(b0["attack_success_rate"]), D.rate(_live["attack_success_rate"])
    t0, t1 = D.rate(b0["utility"]), D.rate(_live["utility"])
    left, right = st.columns(2)
    with left:
        st.markdown("**Attacks that worked**")
        C.versus(("No gate", f"{a0[0]} / {a0[1]}", "hidden attacks that made the agent obey"),
                 ("Final design", f"{a1[0]} / {a1[1]}", "every attack stopped"), tone=("bad", "ok"))
    with right:
        st.markdown("**Tasks the agent completed**")
        C.versus(("No gate", f"{t0[0]} / {t0[1]}", "the agent's own limit"),
                 ("Final design", f"{t1[0]} / {t1[1]}", "the gate cost no tasks"), tone=("ok", "ok"))

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
     "Every test, dev, red-team and combination case with every gate's result. Filter, or show one gate's "
     "mistakes."),
    ("views/how_it_works.py", ":material/account_tree:", "How it works",
     "The pipeline, the evidence, RAG, the question loop, training, and the newest design's layers."),
    ("views/results.py", ":material/monitoring:", "Results",
     "Every number, the safety-vs-annoyance trade-off, two ways of counting questions, and the live agent run."),
    ("views/research.py", ":material/biotech:", "The research",
     "Hypotheses, how the dataset was built, experiments, the project journey, and known limits."),
]
for row in range(0, len(GUIDE), 4):
    cols = st.columns(4)
    for i, (col, (page, icon, title, text)) in enumerate(zip(cols, GUIDE[row:row + 4])):
        with col.container(border=True, height="stretch", key=f"glass_guide_{row + i}"):
            st.page_link(page, label=f"**{title}**", icon=icon)
            st.caption(text)
