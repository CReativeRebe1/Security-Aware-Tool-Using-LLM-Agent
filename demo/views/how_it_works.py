import streamlit as st

from sagate_demo import components as C
from sagate_demo import explain as X
from sagate_demo import flow as F

# Graphviz colours are baked into the drawing, so the diagram is drawn once per theme and CSS shows the matching one.
G_DARK = ('bgcolor="transparent"; node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=11 '
          'color="#334155" fillcolor="#111a2e" fontcolor="#e2e8f0" margin="0.18,0.08"]; edge [color="#64748b" '
          'fontname="Helvetica" fontsize=10 fontcolor="#94a3b8"];')
G_LIGHT = ('bgcolor="transparent"; node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=11 '
           'color="#c7d2fe" fillcolor="#ffffff" fontcolor="#0f172a" margin="0.18,0.08"]; edge [color="#94a3b8" '
           'fontname="Helvetica" fontsize=10 fontcolor="#475569"];')
BLUE = 'fillcolor="#6366f1" fontcolor="white" color="#818cf8"'

C.page_hero("How it works", "From a request to a decision, in plain words",
            "Each tab explains one part. Words with a dotted underline, like [[provenance]], show a short "
            "explanation when you hover over them.")

tabs = st.tabs([":material/route: Pipeline", ":material/fact_check: Evidence", ":material/menu_book: RAG",
                ":material/forum: Questions", ":material/model_training: Training",
                ":material/layers: Final design", ":material/balance: Fair testing"])

with tabs[0]:
    st.markdown("#### From request to decision")
    steps = [
        ("1", "Scenario", "A task from AgentDojo: a user, an inbox or a bank account, maybe an attack hidden inside."),
        ("2", "Agent proposes an action", "The AI agent reads things, then wants to send, delete, share or pay."),
        ("3", "Evidence builder", "Collects provenance, authority, sensitivity, rules (RAG) and simple checks."),
        ("4", "GateInput", "Everything packed into one JSON, the same for every gate."),
        ("5", "Gate (B1 … B5)", "Rules or AI read the GateInput and decide."),
        ("6", "GateOutput", "What is missing → who must decide → the decision."),
        ("7", "Question loop", "ASK_USER / ESCALATE get an answer and go back to the gate. At most 2 rounds."),
        ("8", "Final outcome", "The action runs (ALLOW) or it doesn't (BLOCK)."),
    ]
    C.cards([{"kicker": f"Step {n}", "title": t, "body": b, "status": "info" if n == "5" else ""}
             for n, t, b in steps], four=True)
    C.cards([
        {"kicker": "Key idea", "title": "Only risky actions are checked",
         "body": "Reading (search, open a file) changes nothing and passes. Sending, deleting, sharing and paying "
                 "always stop at the gate."},
        {"kicker": "Key idea", "title": "One input for every gate",
         "body": "Rules, prompted AI and trained AI all get the same GateInput, so the comparison is fair."},
        {"kicker": "Key idea", "title": "Show your working first",
         "body": "The gate first says what is missing and who must decide, and only then gives the decision, like "
                 "showing your working in maths."},
    ])
    st.page_link("views/lab.py", label="See this pipeline run live, on a payment you design, in the Gate Lab",
                 icon=":material/science:")

with tabs[1]:
    st.markdown("#### Four kinds of facts the gate gets")
    C.cards([
        {"kicker": C.icon("travel_explore") + "Provenance", "title": "Where did it come from?", "status": "info",
         "body": "For the action and every argument: did the **user** say it, or did it come from an email, file or "
                 "transaction? An action caused by content is the mark of a prompt injection. Two versions: "
                 "“known” (the benchmark tells us what was injected, best case) and “guessed” (string matching, "
                 "what a real system can do)."},
        {"kicker": C.icon("badge") + "Authority", "title": "Who may approve?", "status": "info",
         "body": "Tables of roles and limits. For example, a user may pay a known payee up to 1,500 and a new payee "
                 "up to 500. Above that, the relationship manager must approve. “The manager already approved it” "
                 "written inside content never counts."},
        {"kicker": C.icon("lock") + "Sensitivity", "title": "How secret, and where to?", "status": "info",
         "body": "Labels PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED on data and destinations. Secret data "
                 "going somewhere less trusted is a warning sign. RESTRICTED data (passwords, reset links) never "
                 "leaves."},
        {"kicker": C.icon("menu_book") + "Handbook rules", "title": "Which rules apply?", "status": "info",
         "body": "The 8 most relevant of our 48 written rules, found by retrieval (next tab)."},
    ], two=True)

with tabs[2]:
    st.markdown("#### RAG: an open-book exam for the gate")
    st.markdown("**RAG** (retrieval-augmented generation) means: first *look up* the relevant text, then put it in "
                "front of the model with the question. The model doesn't have to memorise the rulebook. It reads the "
                "right page.")
    for mode, g in (("dark_only", G_DARK), ("light_only", G_LIGHT)):
        with st.container(key=f"{mode}_rag"):
            st.graphviz_chart("digraph { rankdir=LR; " + g + f"""
              q [label="Facts about the action\\n(only trusted fields)"]; bm [label="Word matching\\n(BM25)"];
              ix [label="Fact → rule index\\n(learned from training labels)"]; fu [label="Merge the two\\nrankings"];
              top [label="Top 8 rules" {BLUE}]; gate [label="Gate input"];
              q -> bm; q -> ix; bm -> fu; ix -> fu; fu -> top -> gate;
            }}""")
    C.cards([
        {"kicker": "Why only trusted fields", "title": "The attacker can't steer it",
         "body": "The search query is built from the action and the evidence, not from email text, so injected text "
                 "can't pull in the wrong rules."},
        {"kicker": "How good", "title": "95% of the key rules found",
         "body": "On the dev set, the top 8 contain 95% of the rules the labellers marked as relevant. Plain word "
                 "matching found about 38% in its top 3."},
    ], two=True)

with tabs[3]:
    st.markdown("#### The four decisions and the question loop")
    st.iframe(F.html_page(), height="content", alt="Animated diagram of the four decisions and the question loop: "
              "ASK_USER and ESCALATE get an answer that goes back to the gate.")
    C.cards([{"kicker": C.chip(d), "title": X.DECISION_PLAIN[d], "body": X.DECISION_EXAMPLE[d]} for d in X.DECISIONS], four=True)
    st.markdown("ASK_USER is for gaps **the user** can fill (which recipient, which file, did you mean it?). ESCALATE "
                "is for things the user **may not** decide alone. After at most 2 rounds, anything still unclear is "
                "blocked. In the tests, a simulated user and a simulated manager answer, and 15% of user replies are "
                "deliberately confusing.")

with tabs[4]:
    st.markdown("#### How the trained gate (B5) is made")
    C.cards([
        {"kicker": "1 · The model", "title": "Qwen3-8B, compressed to 4 bits",
         "body": "An open model with 8 billion parameters. Compression lets it fit on a free 16 GB GPU (Kaggle T4)."},
        {"kicker": "2 · The data", "title": "2,698 examples",
         "body": "The team's labelled cases, rule-based copies of them, and generated cases that mix risk factors in "
                 "new pairs, each with the right decision (ALLOW 944, ASK_USER 603, BLOCK 749, ESCALATE 402)."},
        {"kicker": "3 · The training", "title": "QLoRA: a small add-on",
         "body": "The big model stays frozen; only a small adapter is trained, one pass over the data. The loss "
                 "punishes an ALLOW where BLOCK or ESCALATE was right five times harder than other mistakes."},
        {"kicker": "4 · The answer", "title": "Always a valid answer",
         "body": "The gate doesn't write free text. It scores every allowed value of each field and picks the best, "
                 "which also gives a probability for every decision."},
    ], two=True)
    st.dataframe([
        {"Gate": "B0", "What it is": "No gate at all", "Decisions": "—", "Trained?": "—"},
        {"Gate": "B1", "What it is": "Hand-written rules", "Decisions": "4", "Trained?": "No AI"},
        {"Gate": "B2", "What it is": "Qwen3-8B with instructions", "Decisions": "2 (yes/no)", "Trained?": "No"},
        {"Gate": "B3", "What it is": "Qwen3-8B with instructions", "Decisions": "4", "Trained?": "No"},
        {"Gate": "B4", "What it is": "Qwen3-8B fine-tuned on the same data", "Decisions": "2 (yes/no)", "Trained?": "Yes"},
        {"Gate": "B5", "What it is": "Qwen3-8B fine-tuned, all evidence (ours)", "Decisions": "4", "Trained?": "Yes"},
        {"Gate": "Final", "What it is": "B5 inside the GateExp rule layers (the final system)", "Decisions": "4",
         "Trained?": "Yes"},
        {"Gate": "v1 · v2 · v3", "What it is": "Earlier versions of the trained gate (Run 1, GateExp, factor combinations)",
         "Decisions": "4", "Trained?": "Yes"},
    ], hide_index=True, width="stretch")

with tabs[5]:
    st.markdown("#### The final design: layers of rules around one trained model")
    C.lead("The [[final system]]: the final model B5 inside the [[GateExp]] rule layers. The idea: **the model "
           "judges intent and risk; code keeps "
           "exact state.** An AI is good at reading a request and the text around it, and bad at exact bookkeeping, "
           "like comparing two IBANs digit by digit or adding up today's payments. So exact checks moved into code.")
    C.cards([
        {"kicker": "Layer 1", "status": "info", "title": "Facts",
         "body": "Computed by code and shown to the model: did the user ask (or leave it to an email)? How risky is "
                 "it? Where did the deciding details come from? Is this part of a bigger, split payment? What was "
                 "already paid today?"},
        {"kicker": "Layer 2", "status": "info", "title": "Hard rules first",
         "body": "Policy that no argument may override. If one fires, it decides and the model is not asked: the "
                 "user already said no · a password or reset link would leave · the details came from injected "
                 "content · the user may not approve this alone."},
        {"kicker": "Layer 3", "status": "info", "title": "The trained model",
         "body": "The final model B5: Qwen3-8B with a QLoRA adapter, trained with a cost-matrix loss and cases that "
                 "mix risk factors in new pairs. It reads everything and picks one of the four decisions."},
        {"kicker": "Layer 4", "status": "info", "title": "Checks after",
         "body": "Can only make the answer stricter: confirm a first payment to a new payee, confirm an amount the "
                 "user never stated, confirm a risky action the user did not ask for, confirm a detail the agent "
                 "made up, and route to an approver when only an approver can decide."},
    ], two=True)
    C.note("Every decision keeps a trace of all four layers. In the Playground and Explore, the decisions step "
           "shows it as a coloured path, so you can see exactly which layer decided.")
    st.page_link("views/playground.py", label="See a decision path in the Playground (step 4)",
                 icon=":material/arrow_forward:")

with tabs[6]:
    st.markdown("#### How we keep the test honest")
    C.cards([
        {"kicker": C.icon("call_split") + "Split by family", "title": "No near-copies in the test",
         "body": "Cases are split by scenario family, so near-identical cases never appear in both training and "
                 "test."},
        {"kicker": C.icon("lock") + "Test is the final exam", "title": "Scored once, at the end",
         "body": "Thresholds and the rule index come from training and dev data only. Each final model was scored on "
                 "the test set once, after the model and the code were final. An independent [[blind test set]] of "
                 "about 100 new cases, written from the handbook alone, is the next check."},
        {"kicker": C.icon("receipt_long") + "Traceable", "title": "Every result is stamped",
         "body": "Every result file records the code version and settings it came from."},
    ])
    st.markdown("#### What's next")
    st.markdown("The blind test: about 100 new cases written from the handbook alone, run once. After that, the "
                "team's list: accept a clear user answer on unlabelled-data sharing, more attack-style training cases "
                "where a plain BLOCK is right, re-ask once instead of blocking after a confusing answer, a stronger "
                "agent model, and more AgentDojo domains. For this website: a live connection to the trained model on "
                "a GPU. Today the AI results are the real recorded ones, and only the rules gate runs live.")
