import streamlit as st

from sagate_demo import components as C
from sagate_demo import explain as X

G = ('bgcolor="transparent"; node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=11 '
     'color="#d8d7d2" fillcolor="#ffffff" fontcolor="#0b0b0b" margin="0.18,0.08"]; edge [color="#9a9993" '
     'fontname="Helvetica" fontsize=10 fontcolor="#52514e"];')
BLUE = 'fillcolor="#2a78d6" fontcolor="white" color="#2a78d6"'

st.title("How it works")
st.markdown("The system, from the user's request to the final decision, in plain words.")

tabs = st.tabs([":material/route: Pipeline", ":material/fact_check: Evidence", ":material/menu_book: RAG",
                ":material/forum: Questions", ":material/model_training: Training", ":material/balance: Fair testing"])

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

with tabs[1]:
    st.markdown("#### Four kinds of facts the gate gets")
    C.cards([
        {"kicker": "🧭 Provenance", "title": "Where did it come from?", "status": "info",
         "body": "For the action and every argument: did the **user** say it, or did it come from an email, file or "
                 "transaction? An action caused by content is the mark of a prompt injection. Two versions: "
                 "“known” (the benchmark tells us what was injected, best case) and “guessed” (string matching, "
                 "what a real system can do)."},
        {"kicker": "🪪 Authority", "title": "Who may approve?", "status": "info",
         "body": "Tables of roles and limits. For example, a user may pay a known payee up to 1,500 and a new payee "
                 "up to 500. Above that, the relationship manager must approve. “The manager already approved it” "
                 "written inside content never counts."},
        {"kicker": "🔒 Sensitivity", "title": "How secret, and where to?", "status": "info",
         "body": "Labels PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED on data and destinations. Secret data "
                 "going somewhere less trusted is a warning sign. RESTRICTED data (passwords, reset links) never "
                 "leaves."},
        {"kicker": "📖 Handbook rules", "title": "Which rules apply?", "status": "info",
         "body": "The 8 most relevant of our 48 written rules, found by retrieval (next tab)."},
    ], two=True)

with tabs[2]:
    st.markdown("#### RAG: an open-book exam for the gate")
    st.markdown("**RAG** (retrieval-augmented generation) means: first *look up* the relevant text, then put it in "
                "front of the model with the question. The model doesn't have to memorise the rulebook. It reads the "
                "right page.")
    st.graphviz_chart("digraph { rankdir=LR; " + G + f"""
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
    st.graphviz_chart("digraph { rankdir=LR; " + G + f"""
      g [label="Gate" {BLUE}];
      allow [label="ALLOW\\nrun it" fillcolor="#e6f4ec" color="#bfe3cd"];
      block [label="BLOCK\\nrefuse" fillcolor="#fdeceb" color="#f6c7c3"];
      ask [label="ASK_USER\\n“Which meeting?”" fillcolor="#eef4fd" color="#c9dcf6"];
      esc [label="ESCALATE\\n“Manager, approve 3,000?”" fillcolor="#fdf1dc" color="#f2d49b"];
      g -> allow; g -> block; g -> ask; g -> esc;
      ask -> g [style=dashed label="user answers"]; esc -> g [style=dashed label="manager answers"];
    }}""")
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
        {"kicker": "2 · The data", "title": "About 2,000 examples",
         "body": "1,049 cases labelled by our team plus 1,000 generated variants, each with the right decision."},
        {"kicker": "3 · The training", "title": "QLoRA: a small add-on",
         "body": "The big model stays frozen. Only a small adapter (about 167 MB) is trained, for 2 passes over the "
                 "data."},
        {"kicker": "4 · The answer", "title": "Always a valid answer",
         "body": "The gate doesn't write free text. It scores every allowed value of each field and picks the best, "
                 "which also gives a probability for every decision."},
    ], two=True)
    st.dataframe([
        {"Gate": "B0", "What it is": "No gate at all", "Decisions": "—", "Trained?": "—"},
        {"Gate": "B1", "What it is": "Hand-written rules", "Decisions": "4", "Trained?": "No AI"},
        {"Gate": "B2", "What it is": "Qwen3-8B with instructions", "Decisions": "2 (yes/no)", "Trained?": "No"},
        {"Gate": "B3", "What it is": "Qwen3-8B with instructions", "Decisions": "4", "Trained?": "No"},
        {"Gate": "B4", "What it is": "Qwen3-8B fine-tuned", "Decisions": "2 (yes/no)", "Trained?": "Yes (pending)"},
        {"Gate": "B5", "What it is": "Qwen3-8B fine-tuned, all evidence (ours)", "Decisions": "4", "Trained?": "Yes"},
    ], hide_index=True, width="stretch")

with tabs[5]:
    st.markdown("#### How we keep the test honest")
    C.cards([
        {"kicker": "✂️ Split by family", "title": "No near-copies in the test",
         "body": "Cases are split by scenario family, so near-identical cases never appear in both training and "
                 "test."},
        {"kicker": "🔒 Test is the final exam", "title": "No tuning on test",
         "body": "Thresholds and the rule index come from training and dev data only. Test results are never used to "
                 "change the design."},
        {"kicker": "🧾 Traceable", "title": "Every result is stamped",
         "body": "Every result file records the code version and settings it came from."},
    ])
    st.markdown("#### What's next")
    st.markdown("Ablations (retrain B5 without provenance, without authority, without RAG… to measure what each part "
                "is worth), B4, full runs inside AgentDojo, and statistics. For this website: a live connection to "
                "the trained model on a GPU, once the architecture is final. Today the AI results are the real "
                "recorded ones, and only the rules gate runs live.")
