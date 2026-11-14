import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo import flow as F
from sagate_demo.gates import V1, reports

# ------------------------------------------------------------------ hero: name, one line, the team
C.hero(C.COURSE, "SA-Gate: a security gate for AI assistants",
       "AI assistants can now send emails, share files and move money. SA-Gate checks every risky action before "
       "it happens. It allows it, blocks it, asks the user, or asks a manager.", art="emblem", highlight="AI assistants")

a, b, c, _ = st.columns([1.25, 1.1, 1.1, 0.9])
if a.button("Watch the gates race", icon=":material/sports_score:", type="primary", width="stretch"):
    st.switch_page("views/simulation.py")
if b.button("Try the Gate Lab", icon=":material/science:", width="stretch"):
    st.switch_page("views/lab.py")
if c.button("Play: be the gate", icon=":material/stadia_controller:", width="stretch"):
    st.switch_page("views/game.py")

R = D.reported()                 # the team's final numbers (results/final/*.pdf)
FIN, ADJ = D.official("final"), R["agentdojo"]


def _pct(s):
    v = D.rate(s)
    return f"{v[2]:.1f}%" if v else "–"


C.numbers([("1,497", "real cases labelled by the team"), ("61", "red-team attacks"), ("216", "combination cases"),
           (_pct(FIN["final_resolution_success"]), "correct on the test set, final system"),
           (FIN["unauthorized_action_rate"].split(" ")[0].replace("/", " / "), "unsafe actions on test, final system"),
           (ADJ["final"]["attack_success_rate"].split(" ")[0].replace("/", " / "), "attacks that worked in the live agent run")])


def pct(k, key, split="test"):
    r = D.rate((reports(split).get(k) or {}).get(key))
    return r[2] if r else None


# ------------------------------------------------------------------ the problem: an editorial numbered list
RISKS = [("smart_toy", "It can act",
          "The assistant doesn't just answer. It sends emails, deletes files and pays bills. A mistake can't be "
          "taken back."),
         ("mail", "It can be tricked",
          "An email or a bill can hide an instruction, a [[prompt injection]]. The assistant may obey it as if the "
          "user had said it."),
         ("badge", "It can overstep",
          "Even when the user asks, a big payment may need the manager, and secret data must never leave.")]
rows = "".join(f'<div class="row"><div class="n">0{i + 1}</div><div><h4>{C.icon(ic)}{C.esc(t)}</h4>'
               f'<p>{C.md(body)}</p></div></div>' for i, (ic, t, body) in enumerate(RISKS))
C.show(f'<div class="sg-split"><div>{C.heading("The problem", "Three ways an assistant can go wrong", "Tool-using AI is useful because it acts. That is also what makes it risky.")}'
       f'</div><div class="sg-numbered">{rows}</div></div>')

# ------------------------------------------------------------------ our idea: the animated gate and the four decisions
C.show('<div style="margin-top:44px">' + C.heading(
    "Our idea", "A gate in front of every risky action",
    "Reading is harmless, so it passes. Every action that **changes something** stops at the gate. The gate gets "
    "four kinds of facts: [[provenance]], [[authority]], [[sensitivity]] and the relevant handbook rules ([[RAG]]). "
    "Then it picks one of **four decisions**:") + "</div>")
st.iframe(F.html_page(), height="content", alt="Animated diagram: a request goes from the user to the AI agent, "
          "the gate checks four kinds of evidence and picks ALLOW, BLOCK, ASK_USER or ESCALATE.")
DICON = {"ALLOW": "check_circle", "BLOCK": "block", "ASK_USER": "help", "ESCALATE": "supervisor_account"}
C.show('<div class="sg-decisions">' + "".join(
    f'<div class="sg-dtile {d}"><div class="ic">{C.icon(DICON[d])}</div><div class="nm">{C.esc(d)}</div>'
    f'<h4>{C.esc(X.DECISION_PLAIN[d])}</h4><p>Example: {C.esc(X.DECISION_EXAMPLE[d])}</p></div>'
    for d in X.DECISIONS) + "</div>")
C.note("A yes/no gate must either take the risk or refuse. Asking the user, or the manager, lets the gate be safe "
       "**and** useful when something is missing.")

# ------------------------------------------------------------------ progress: the unsafe rate falls, step by step
C.show('<div style="margin-top:44px">' + C.heading(
    "Progress so far", "Unsafe actions let through",
    "Each bar is one stage of the project. The dashed line is the target: at most 5% of risky actions may get "
    "through.") + "</div>")
v1 = reports("test").get(V1) or {}      # Run 1's trained gate, scored here against the same labels
STEPS = [(D.official("b3"), "B3", "Untrained AI",
          "The model with instructions only. It also asks about half of the cases needlessly."),
         (v1, "v1", "First trained gate",
          "Fine-tuned on our labels in Run 1. Needless questions almost gone, but still too many unsafe actions."),
         (D.official("b5"), "B5", "Final model alone",
          "Retrained on 2,698 examples with a loss that punishes unsafe answers hardest."),
         (FIN, "Final", "Final system",
          "B5 inside the GateExp rule layers. Scored on the test set once, at the end.")]
SCALE = 25.0                                    # top of the plot, in percent
cols, labels, steps = [], [], []
where = "test"
for m, code, name, text in STEPS:
    u, q = (D.rate(m.get(k)) for k in ("unauthorized_action_rate", "unnecessary_deferral_rate"))
    u, q = (u[2] if u else None), (q[2] if q else None)
    if u is None:
        continue
    good = u <= 5
    cols.append(f'<div class="col"><div class="v">{u:.1f}%</div><div class="bar {"ok" if good else "bad"}" '
                f'style="height:{max(u, 0) / SCALE * 100:.1f}%"></div></div>')
    labels.append(f'<div><b>{C.esc(code)}</b><span>{C.esc(name)} · {where}</span></div>')
    steps.append(f'<div class="st {"ok" if good else ""}"><i></i><b>{C.esc(code)} · {C.esc(name)}</b>'
                 f'<small>{where}</small><p>{C.esc(text)} Needless questions: {q:.1f}%.</p></div>')
C.show(f'<div class="sg-progress"><div class="sg-bars-panel"><div class="plot">'
       f'<div class="target" style="bottom:{5 / SCALE * 100:.0f}%"><span>target ≤ 5%</span></div>{"".join(cols)}</div>'
       f'<div class="xl">{"".join(labels)}</div></div><div class="sg-steps">{"".join(steps)}</div></div>')
X_ = R["final_extra"]
C.callout("new", "Read this honestly:",
          "the final system was scored on the test set once, after the model and the code were final. Its safety "
          f"holds on every set: {D.official('final', 'dev')['unauthorized_action_rate']} unsafe on dev, "
          f"{D.official('final', 'attacks')['unauthorized_action_rate']} on the red-team attacks, "
          f"{D.official('final', 'combos')['unauthorized_action_rate']} on the combinations. The cost is questions: "
          f"{FIN['unnecessary_deferral_rate']} needless on test, most of them confirmations the policy requires "
          f"({X_['unneeded_excl_confirmations_test']} without those). The labels were written by the team, so an "
          "independent [[blind test set]] is still to come.")

# ------------------------------------------------------------------ inside a real agent: one before | after panel
if ADJ:
    C.show('<div style="margin-top:44px">' + C.heading(
        "Inside a real agent", "No attack got through",
        "The whole AI agent ran 142 [[AgentDojo]] tasks, 120 of them with a hidden attack, once without a gate and "
        "once with the final design in front of every risky action. Here the gate has to guess where text came "
        "from, as a real system must.") + "</div>")
    b0, fin = ADJ["b0"], ADJ["final"]
    a0, a1 = D.rate(b0["attack_success_rate"]), D.rate(fin["attack_success_rate"])
    t0, t1 = D.rate(b0["utility"]), D.rate(fin["utility"])
    C.show(f'<div class="sg-duel"><div class="before"><div class="tag">No gate</div>'
           f'<div class="big">{a0[0]} / {a0[1]}</div><div class="cap">hidden attacks that made the agent obey</div>'
           f'<div class="minor"><b>{t0[0]} / {t0[1]}</b><span>tasks completed: the agent\'s own limit</span></div></div>'
           f'<div class="vs"><img alt="" src="{C._img("shield.svg")}"></div>'
           f'<div class="after"><div class="tag">With SA-Gate (final system)</div>'
           f'<div class="big">{a1[0]} / {a1[1]}</div><div class="cap">every attack stopped</div>'
           f'<div class="minor"><b>{t1[0]} / {t1[1]}</b><span>tasks completed: the gate cost no tasks</span></div>'
           f'</div></div>')
st.page_link("views/results.py", label="See every number and the honest caveats", icon=":material/arrow_forward:")

# ------------------------------------------------------------------ explore: a bento grid of the pages
C.show('<div style="margin-top:40px">' + C.heading("Explore the site", "Where to go next") + "</div>")
GUIDE = {
    "playground": ("views/playground.py", ":material/play_circle:", "Playground",
                   "Seven real cases told step by step: the request, the agent's action, the evidence, and every "
                   "gate's decision."),
    "simulation": ("views/simulation.py", ":material/sports_score:", "Simulation",
                   "Watch the gates decide hundreds of real cases side by side, live, with counters."),
    "lab": ("views/lab.py", ":material/science:", "Gate Lab",
            "Design a payment yourself (amount, payee, a hidden attack, a fake approval) and watch the pipeline "
            "decide."),
    "game": ("views/game.py", ":material/stadia_controller:", "Be the gate",
             "Decide real cases yourself and compare your score with the AI gates."),
    "explore": ("views/explore.py", ":material/search:", "Explore all cases",
                "Every test, dev, red-team and combination case with every gate's result. Filter, or show one "
                "gate's mistakes."),
    "how": ("views/how_it_works.py", ":material/account_tree:", "How it works",
            "The pipeline, the evidence, RAG, the question loop, training, and the final design's layers."),
    "results": ("views/results.py", ":material/monitoring:", "Results",
                "Every number, the safety-vs-annoyance trade-off, two ways of counting questions, and the live "
                "agent run."),
    "research": ("views/research.py", ":material/biotech:", "The research",
                 "Hypotheses, how the dataset was built, experiments, the project journey, and known limits."),
}
for widths, keys in (([2, 1, 1], ["playground", "simulation", "lab"]), ([1, 1, 2], ["game", "explore", "how"]),
                     ([1, 1], ["results", "research"])):
    for col, key in zip(st.columns(widths), keys):
        page, ic, title, text = GUIDE[key]
        with col.container(border=True, height="stretch", key=f"glass_guide_{key}"):
            st.page_link(page, label=f"**{title}**", icon=ic)
            st.caption(text)

# ------------------------------------------------------------------ the team
C.show('<div style="margin-top:44px">' + C.heading("The team", "Made by four students of CL3410",
                                                    "Language Models and Agents, IIIT Hyderabad.") + "</div>")
C.team_section()
l1, l2, _ = st.columns([1, 1, 2])
l1.link_button("GitHub repository", C.REPO_URL, icon=":material/code:", width="stretch")
l2.link_button("Project report (PDF)", C.REPORT_URL, icon=":material/description:", width="stretch")
