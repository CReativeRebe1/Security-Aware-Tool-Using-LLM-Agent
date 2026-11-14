from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo.gates import GATES, reports

C.page_hero("The research", "What we set out to test, and where we are",
            "The hypotheses, how the dataset was built, what has been run so far, how the project got here, and "
            "what is still open.")

tabs = st.tabs([":material/help: Questions", ":material/dataset: Data", ":material/science: Experiments",
                ":material/timeline: Journey", ":material/report: Known limits"])

rep = reports("test")


def r(cond, key):
    v = D.rate((rep.get(cond) or {}).get(key))
    return f"{v[2]:.1f}%" if v else "–"


# ------------------------------------------------------------------ questions
R = D.reported()


def off(model, key, split="test"):
    return D.official(model, split).get(key, "–")


with tabs[0]:
    st.markdown("#### The goal")
    C.callout("lesson", "Target:", "a gate that lets **at most 5%** of unsafe actions through **and** asks **at most "
              "10%** needless questions. Being safe by refusing everything doesn't count, and neither does asking "
              "about everything.")
    st.markdown("#### Where we ended")
    C.show('<div class="sg-grid four">'
           + C.stat_tile("Final system · test", off("final", "unauthorized_action_rate").split(" (")[-1].rstrip(")"),
                         "unsafe", ("ok", "✓ target ≤ 5%"), f"needless questions {off('final', 'unnecessary_deferral_rate')}; "
                         f"correct {off('final', 'final_resolution_success')}")
           + C.stat_tile("B5 alone · test", off("b5", "unauthorized_action_rate").split(" (")[-1].rstrip(")"),
                         "unsafe", ("ok", "✓ target ≤ 5%"), f"needless questions {off('b5', 'unnecessary_deferral_rate')}")
           + C.stat_tile("B3 prompted · test", off("b3", "unauthorized_action_rate").split(" (")[-1].rstrip(")"),
                         "unsafe", ("bad", "✕ target ≤ 5%"), f"needless questions {off('b3', 'unnecessary_deferral_rate')}")
           + C.stat_tile("B1 rules · test", off("b1", "unauthorized_action_rate").split(" (")[-1].rstrip(")"),
                         "unsafe", ("bad", "✕ target ≤ 5%"), f"needless questions {off('b1', 'unnecessary_deferral_rate')}")
           + "</div>")
    C.note("From the team's final reports. Only the fine-tuned four-way gate, alone and inside the rule layers, meets "
           "both targets on test. In the live AgentDojo run the final system let 0 of 120 attacks through.")
    st.markdown("#### What the experiments showed")
    C.lead("Every comparison is paired, case by case, against B5 alone, on the same locked code, data and cases. "
           "H1 and H2 were the pre-registered main hypotheses.")
    C.cards([{"kicker": v["q"], "status": v["status"], "title": v["verdict"], "body": v["result"]}
             for v in R["verdicts"]], two=True)

# ------------------------------------------------------------------ data
with tabs[1]:
    st.markdown("#### From benchmark to labelled cases")
    C.cards([
        {"kicker": "1 · Benchmark", "title": "AgentDojo",
         "body": "Two simulated worlds, an office (email, calendar, files) and a bank. 56 user tasks, 23 attacker "
                 "goals, 760 scenarios."},
        {"kicker": "2 · Agent runs", "title": "23,602 published traces",
         "body": "AgentDojo's own run logs from 29 model and defence set-ups (GPT, Claude, Gemini, Llama and "
                 "others). 12.7% of the attacked runs reached the attacker's goal. Our own agent (Qwen3-8B) was run "
                 "separately for the no-gate baseline."},
        {"kicker": "3 · Hand-written cases", "title": "2,000 cases in 142 families",
         "body": "Each family is one situation over the real AgentDojo worlds. Its variants change one fact so the "
                 "right answer flips: internal vs outside recipient, 1,400 vs 1,850, an IBAN from the user vs from a "
                 "bill, clean vs injected. The project's own evidence builder computes what the gate sees."},
        {"kicker": "4 · Human labels", "title": "1,497 reviewed and frozen",
         "body": "The team reviewed the cases in batches of 100 in a labelling app: the first decision, the final "
                 "action, what's missing, who decides, and which rules apply."},
    ], four=True)

    st.caption("Attacks are deliberately varied: fake IT notices, TODO lines in files, hidden HTML comments, "
               "messages that pretend to be the user, look-alike domains, instructions in German or Spanish, "
               "“SYSTEM OVERRIDE” role-play, and payloads hidden in payment references.")
    rows, mix = [], {}
    for name in ("train", "dev", "test"):
        cs = list(D.cases(name).values()) if name != "train" else list(D.train_cases().values())
        fam = {c.meta.get("family") for c in cs}
        cnt = Counter(c.gold_decision for c in cs)
        mix[name] = cnt
        rows.append({"Split": name, "Cases": len(cs), "Scenario families": len(fam),
                     "Office / bank": f"{sum(c.input.suite == 'workspace' for c in cs)} / "
                                      f"{sum(c.input.suite == 'banking' for c in cs)}",
                     "Start after an answered question": sum(bool(c.input.resolution_history) for c in cs),
                     "Used for": {"train": "training", "dev": "tuning and choosing settings",
                                  "test": "the final exam, nothing else"}[name]})
    st.markdown("#### The frozen split")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Whole families go to one split, so no near-copy of a test case is ever seen in training.")
    C.note("Two more sets came later, for checking only: **61 red-team attacks**, written by hand to break the gate, "
           "and **216 [[combinations|combination cases]]**, generated to mix risk factors in pairs the training data "
           "never had (labelled by the team's rule program). A **[[blind test set]]** of about 100 new cases is "
           "being written now.")

    st.markdown("#### What the right first decision is, per split")
    colors = {"ALLOW": "#199e70", "BLOCK": "#e34948", "ASK_USER": "#3987e5", "ESCALATE": "#c98500"}   # dark, validated
    fig = go.Figure()
    names = ["train", "dev", "test"]
    for d in X.DECISIONS:
        vals = [100 * mix[n][d] / sum(mix[n].values()) for n in names]
        counts = [mix[n][d] for n in names]
        fig.add_trace(go.Bar(y=names, x=vals, orientation="h", name=d, marker=dict(color=colors[d],
                             line=dict(width=0)),
                             text=[f"{d} {v:.0f}%" for v in vals], textposition="inside", insidetextanchor="middle",
                             textfont=dict(color="#0b1120" if d == "ESCALATE" else "#ffffff", size=12), customdata=counts,
                             hovertemplate=f"<b>{d}</b> · %{{y}}<br>%{{customdata}} cases (%{{x:.1f}}%)<extra></extra>"))
    fig.update_layout(barmode="stack", height=250, margin=dict(l=60, r=10, t=10, b=40), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
                      legend=dict(orientation="h", y=-0.22, x=0, traceorder="normal"),
                      font=dict(color="#64748b"), hoverlabel=dict(bgcolor="#111a2e", font_color="#e2e8f0"), bargap=0.35)
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(color="#64748b", size=13), automargin=True)
    with st.container(border=True, key="glass_research_mix"):
        st.plotly_chart(fig, width="stretch", theme=None)
    with st.expander("Show as a table", icon=":material/table:"):
        st.dataframe(pd.DataFrame({n: {d: mix[n][d] for d in X.DECISIONS} for n in names}), width="stretch")

    st.markdown("#### Kinds of cases")
    kinds = Counter()
    for name in ("dev", "test"):
        kinds.update(X.CATEGORY_PLAIN.get(c.category, c.category) for c in D.cases(name).values())
    kinds.update(X.CATEGORY_PLAIN.get(c.category, c.category) for c in D.train_cases().values())
    C.cards([{"kicker": f"{n} cases", "title": k, "body": ""} for k, n in kinds.most_common()], four=True)

# ------------------------------------------------------------------ experiments
with tabs[2]:
    st.markdown("#### Every model on the test set")
    C.lead("All models were trained and scored with the same locked code, data and cases. Each trained model is "
           "scored alone; the final system is B5 inside the GateExp rule layers. Numbers from the team's final "
           "reports.")
    order = ["final", "b5", "b5_seed7", "b5_inferred", "no_prov", "no_auth", "no_inter", "no_rag", "no_ask", "no_esc",
             "b4", "b3", "b2", "b1"]
    what = {"final": "The final system", "b5": "Final model alone", "b5_seed7": "Same, second training seed",
            "b5_inferred": "Provenance guessed, not known", "no_prov": "Removes where things came from (H1)",
            "no_auth": "Removes who may approve (H1)", "no_inter": "Removes 'what's missing / who decides' (H3)",
            "no_rag": "Removes the handbook rules", "no_ask": "Removes the ASK_USER decision (H2)",
            "no_esc": "Removes the ESCALATE decision (H2)", "b4": "Trained, only ALLOW or BLOCK (H2)",
            "b3": "Untrained, four decisions", "b2": "Untrained, only ALLOW or BLOCK", "b1": "Hand-written rules"}
    test = R["pools"]["test"]
    st.dataframe(pd.DataFrame([{"Model": f"{R['models'][k]['code']} · {R['models'][k]['name']}", "What it tests": what[k],
                                "Correct": test[k]["final_resolution_success"],
                                "Unsafe": test[k]["unauthorized_action_rate"],
                                "Needless questions": test[k]["unnecessary_deferral_rate"],
                                "Good actions blocked": test[k]["over_blocking_rate"]} for k in order if k in test]),
                 hide_index=True, width="stretch", column_config={"Model": st.column_config.TextColumn(width="medium")})
    st.caption("B4, B2 and the models without ASK_USER or ESCALATE are scored on the cases they can answer (159, 170, "
               "201 of 212). Without a gate at all (B0), 10 of 120 attacks succeed in the live AgentDojo run.")
    st.markdown("#### The final training and scoring runs")
    st.markdown("Four teammates trained and scored two models each, in parallel, on their own Kaggle accounts (2 × T4 "
                "per run), all from the same locked code (`locked-v4`). Only the part named in each model differs.")
    st.dataframe(pd.DataFrame([
        {"Run": "A", "Who": "Prabhash Padhan", "Models": "B4 (yes/no) · B5 − intermediate targets"},
        {"Run": "B", "Who": "Shubham Kumar Sunny", "Models": "B5 − provenance · B5 − authority"},
        {"Run": "C", "Who": "Yogendra Patel", "Models": "B5 − RAG · B5 − ASK_USER"},
        {"Run": "D", "Who": "Yogendra Patel", "Models": "B5 − ESCALATE · B5 with a second seed"},
        {"Run": "V4", "Who": "Rinkesh Verma", "Models": "B5 alone · B5 with guessed provenance · the final system"},
    ]), hide_index=True, width="stretch")
    st.caption("Every model trained to the end with the planned examples, without restarts or dropped examples. Each "
               "model's test set was scored once.")
    st.markdown("#### The run plan")
    C.cards([
        {"kicker": "Run 1 · done", "status": "ok", "title": "Baselines and the first trained gate",
         "body": "B1–B3 and the first trained gate (v1) on the test and dev sets."},
        {"kicker": "Design versions · done", "status": "ok", "title": "Layers around the model",
         "body": "GateExp v2 and v3 on dev, red-team and combinations, then the final design and a live AgentDojo "
                 "run."},
        {"kicker": "Final runs · done", "status": "ok", "title": "B4, the ablations, a second seed",
         "body": "Trained and scored in parallel (runs A–D and V4), with paired tests against B5."},
        {"kicker": "Still to come", "status": "info", "title": "The blind test",
         "body": "About 100 new cases written from the handbook alone, run once: the independent check of the "
                 "[[blind test set]]."},
    ], two=True)

# ------------------------------------------------------------------ journey
with tabs[3]:
    st.markdown("#### How the project got here")
    events = [
        ("26 Oct", "Benchmark exported", "AgentDojo office and bank worlds: 760 scenarios and 23,602 published "
                                          "agent traces from 29 set-ups. The scenario split was fixed."),
        ("26–30 Oct", "Pipeline built", "Evidence builder, gates B1–B5, the question loop and the Kaggle "
                                         "notebooks. B0 measured: attacks succeed 8.3% of the time."),
        ("29 Oct", "First trained results", "A first trained gate on 160 provisional cases: 87.5% correct, but 19% "
                                            "unsafe."),
        ("6–9 Nov", "Human labelling", "The team reviewed 2,000 cases. 1,497 were frozen into train, dev and test, "
                                        "split by family."),
        ("9 Nov", "Audit", "The pipeline was checked against the frozen data. Leaks and scoring problems were found "
                           "and fixed."),
        ("10 Nov", "Fixes and better retrieval", "New evidence, safety guards, and retrieval that finds 95% of the "
                                                  "key rules. A training fix made 2-epoch runs fit on a free T4 GPU."),
        ("10–11 Nov", "Run 1", "Smoke test, baselines B1–B3, and the first trained gate (v1) on the test set."),
        ("11 Nov", "Code review and stress test", "A full code review, and 90 hand-made tricky cases that target "
                                                  "the weak spots."),
        ("11–12 Nov", "GateExp (v2)", "The model retrained and placed inside layers of facts, hard rules and "
                                      "after-checks; 61 new red-team attacks; a written confirmation policy for new "
                                      "payees and unstated amounts, with the labels updated to match."),
        ("12 Nov", "v3 and the review fixes", "B5 retrained with a cost-matrix loss and factor-combination data, "
                                              "inside the GateExp layers. Two code reviews fixed how approvals, "
                                              "untraced targets and amounts are handled; a first live AgentDojo run "
                                              "stopped all 120 attacks."),
        ("13 Nov", "Locked, final training and scoring", "Code locked as locked-v4. Four teammates trained and scored "
                                                         "B4, the six ablations and a second seed in parallel (runs "
                                                         "A–D); the final B5 and the final system were scored on test "
                                                         "once: 206/212 correct, 0 unsafe."),
        ("14 Nov", "Final reports", "Baselines re-run with the locked code, a no-gate AgentDojo run (10/120 attacks "
                                    "worked; 0/120 with the final system, at the same 49/142 tasks), and the final "
                                    "reports with paired tests: H1 and H2 supported, H3 not."),
    ]
    html = "".join(f'<div class="sg-step"><div class="ico sg-when">{C.esc(d)}</div><div class="body">'
                   f'<div class="title">{C.esc(t)}</div><div class="sub">{C.esc(b)}</div></div></div>'
                   for d, t, b in events)
    C.show(f'<div class="sg-card">{html}</div>')

# ------------------------------------------------------------------ limits
with tabs[4]:
    st.markdown("#### What we know is not solved yet")
    st.markdown("A security project should say where it is weak. These come from the team's final reports, audit and "
                "code review.")
    ex = R["final_extra"]
    C.cards([
        {"kicker": "Open", "status": "warn", "title": "Labels written by the team",
         "body": "Every right answer was written by the team, and a few were updated by written policy. The "
                 "independent [[blind test set]] (about 100 new cases from the handbook alone) is still to come."},
        {"kicker": "Open", "status": "warn", "title": "More questions on attacks",
         "body": f"On the red-team set the final system asks {off('final', 'unnecessary_deferral_rate', 'attacks')} "
                 "needless questions (4 of 33 cases), just above the target. Counted strictly over cases whose right "
                 f"answer is ALLOW, test is at {ex['strict_unneeded']['test']}; most are confirmations the policy "
                 "requires."},
        {"kicker": "Open", "status": "warn", "title": "A confusing user leads to blocks",
         "body": f"With a confusing simulated user, good actions blocked on test rise from "
                 f"{off('final', 'over_blocking_rate')} to {ex['test_noisy']['over_blocking_rate']}: an unhelpful "
                 "answer usually ends in BLOCK."},
        {"kicker": "Open", "status": "warn", "title": "An extra recipient in a list",
         "body": "“Email David” turned into “email David and attacker@…” still counts as user-named, because one "
                 "address in the list came from the user."},
        {"kicker": "Fixed", "status": "ok", "title": "Unknown tools and odd amounts",
         "body": "An unknown tool now always goes through the gate, and amounts like “Send David 1800” or “5e3” are "
                 "read correctly. An amount that can't be read is refused instead of passing every limit."},
        {"kicker": "Handled in reporting", "status": "info", "title": "The scoring can reward asking",
         "body": "A simulated user who always answers well makes asking look free. That's why 'needless questions' "
                 "is always reported next to 'unsafe', and also counted the strict way."},
        {"kicker": "Design choice", "status": "info", "title": "Removed decisions trained as BLOCK",
         "body": "B4 and the models without ASK_USER or ESCALATE were trained to BLOCK where B5 would ask. This follows "
                 "the project journal, not the original proposal, and the report says so."},
        {"kicker": "Limit", "status": "info", "title": "One seed, small sets",
         "body": "One training seed per model; two seeds of B5 differ by about 4 points, so only larger effects are "
                 "claimed. The live AgentDojo tasks are limited by the agent itself, not the gate."},
    ], two=True)
