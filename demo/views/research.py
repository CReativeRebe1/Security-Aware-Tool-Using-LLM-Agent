from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo.gates import GATES, NEWEST, PREV_GX, reports

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
with tabs[0]:
    st.markdown("#### The goal")
    C.callout("lesson", "Target:", "a gate that lets **at most 5%** of unsafe actions through **and** asks **at most "
              "10%** needless questions. Being safe by refusing everything doesn't count, and neither does asking "
              "about everything.")
    st.markdown("#### Three hypotheses")
    C.cards([
        {"kicker": "H1 · Evidence", "status": "info",
         "title": "Structured evidence makes the gate better",
         "body": "Provenance, authority, sensitivity and handbook rules should beat a gate without them. **How we "
                 "test it:** retrain B5 with one piece removed at a time (the ablations). **Status:** trained on 13 Nov "
                 f"(final runs B and C); scores come with the final scoring run. **Early sign:** when provenance is only guessed, B5's unsafe rate rises from "
                 f"{r('b5_qlora_4way', 'unauthorized_action_rate')} to "
                 f"{r('b5_inferred_prov', 'unauthorized_action_rate')}."},
        {"kicker": "H2 · Four decisions", "status": "info",
         "title": "Asking and escalating beat a plain yes/no",
         "body": "**How we test it:** B5 (four decisions) against B4 (yes/no), trained on the same data. "
                 "**Status:** B4 trained on 13 Nov (final run A); scoring next. **Early sign** (untrained AI): the yes/no B2 blocks "
                 f"{r('b2_prompt_binary', 'over_blocking_rate')} of good actions, the four-way B3 "
                 f"{r('b3_prompt_4way', 'over_blocking_rate')}. Caveat: the scoring itself favours four decisions "
                 "(see Results)."},
        {"kicker": "H3 · Show your working", "status": "info",
         "title": "Saying what's missing first helps",
         "body": "The gate names the missing evidence and who must decide before the decision. **How we test "
                 "it:** retrain B5 without those two fields. **Status:** trained on 13 Nov (final run A); scoring "
                 "next."},
    ])
    st.markdown("#### Where we stand")
    devr = reports("dev")
    dv = lambda key: (lambda v: f"{v[2]:.1f}%" if v else "–")(D.rate((devr.get(NEWEST) or {}).get(key)))
    C.show('<div class="sg-grid four">'
           + C.stat_tile("Final design GX3 · dev", dv("unauthorized_action_rate"), "unsafe",
                         ("ok", "✓ target ≤ 5%"), f"needless questions {dv('unnecessary_deferral_rate')}; "
                         "test held back")
           + C.stat_tile("GateExp GX · test", r(PREV_GX, "unauthorized_action_rate"), "unsafe",
                         ("ok", "✓ target ≤ 5%"), f"needless questions {r(PREV_GX, 'unnecessary_deferral_rate')}")
           + C.stat_tile("Trained gate B5", r("b5_qlora_4way", "unauthorized_action_rate"), "unsafe",
                         ("bad", "✕ target ≤ 5%"), f"needless questions {r('b5_qlora_4way', 'unnecessary_deferral_rate')}")
           + C.stat_tile("Rules gate B1", r("b1_rules", "unauthorized_action_rate"), "unsafe",
                         ("bad", "✕ target ≤ 5%"), f"needless questions {r('b1_rules', 'unnecessary_deferral_rate')}")
           + "</div>")
    C.note("Scored the same way, against the frozen labels. GateExp (GX) meets the safety target on test, but some "
           "of its rules were found on test failures. So the final design (GX3, 12 Nov) is shown on dev and is "
           "[[held back]] from test until one final run. In the live AgentDojo run it let 0 of 120 attacks through.")

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
    colors = {"ALLOW": "#008300", "BLOCK": "#e34948", "ASK_USER": "#2a78d6", "ESCALATE": "#eda100"}
    fig = go.Figure()
    names = ["train", "dev", "test"]
    for d in X.DECISIONS:
        vals = [100 * mix[n][d] / sum(mix[n].values()) for n in names]
        counts = [mix[n][d] for n in names]
        fig.add_trace(go.Bar(y=names, x=vals, orientation="h", name=d, marker=dict(color=colors[d],
                             line=dict(width=2, color="#ffffff")),
                             text=[f"{d} {v:.0f}%" for v in vals], textposition="inside", insidetextanchor="middle",
                             textfont=dict(color="#ffffff", size=12), customdata=counts,
                             hovertemplate=f"<b>{d}</b> · %{{y}}<br>%{{customdata}} cases (%{{x:.1f}}%)<extra></extra>"))
    fig.update_layout(barmode="stack", height=250, margin=dict(l=60, r=10, t=10, b=40), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
                      legend=dict(orientation="h", y=-0.22, x=0, traceorder="normal"),
                      font=dict(color="#52514e"), hoverlabel=dict(bgcolor="white"))
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(color="#0b0b0b", size=13), automargin=True)
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
    st.markdown("#### What we compare")
    devr = reports("dev")
    live = (D.e2e().get(NEWEST) or {}).get("test/all") or {}

    def status(key):
        if key == NEWEST:
            return "✓ dev, red-team, combinations, live · test held back"
        if key == "b4_qlora_binary":
            return "✓ trained 13 Nov · scoring next"
        return "✓ done" if key in rep else "… pending"

    def result(key):
        m = rep.get(key) or (devr.get(key) if key == NEWEST else None)
        if not m:
            return "–"
        where = " (dev)" if key == NEWEST else ""
        out = f"{m.get('final_resolution_success', '')} correct · {m.get('unauthorized_action_rate', '')} unsafe{where}"
        if key == NEWEST and live:
            out += f" · live: attacks {live.get('attack_success_rate')}"
        return out

    rows = [{"Gate": "B0", "What it is": "No gate at all (the agent alone)", "Status": "✓ measured live",
             "Result so far": "Attacks succeed 10/120 (8.3%); tasks done 49/142 (34.5%)"}]
    for k, g in GATES.items():
        rows.append({"Gate": g.code, "What it is": g.blurb, "Status": status(k), "Result so far": result(k)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"What it is": st.column_config.TextColumn(width="large")})
    st.markdown("#### Ablations: what is each part worth?")
    st.markdown("B5 is retrained with one part removed, on the final recipe. The drop in quality is that part's "
                "value.")
    runs = D.training_runs()
    where = {m["condition"]: (letter, m) for letter, r in runs.items() for m in r.get("models", [])}

    def tstat(cond, letter):
        if cond in where:
            return f"✓ trained (run {where[cond][0]}) · scoring next"
        return f"… training (run {letter})"

    st.dataframe(pd.DataFrame([
        {"Variant": "B5 − provenance", "Removes": "where things came from", "Tests": "H1",
         "Status": tstat("b5_v4_no_prov", "B")},
        {"Variant": "B5 − authority", "Removes": "who may approve", "Tests": "H1", "Status": tstat("b5_v4_no_auth", "B")},
        {"Variant": "B5 − RAG", "Removes": "the handbook rules", "Tests": "H1", "Status": tstat("b5_v4_no_rag", "C")},
        {"Variant": "B5 − intermediate", "Removes": "'what's missing / who decides'", "Tests": "H3",
         "Status": tstat("b5_v4_no_inter", "A")},
        {"Variant": "B5 − ASK", "Removes": "the ASK_USER decision", "Tests": "H2", "Status": tstat("b5_v4_no_ask", "C")},
        {"Variant": "B5 − ESCALATE", "Removes": "the ESCALATE decision", "Tests": "H2",
         "Status": tstat("b5_v4_no_esc", "D")},
    ]), hide_index=True, width="stretch")
    st.markdown("#### The final training runs (13 Nov)")
    st.markdown("Four teammates trained two models each, in parallel, on Kaggle (2 × T4 per run), all from the same "
                "locked code (`locked-v4`). Only the part named in each model differs.")
    trows = []
    for letter, plan in (("A", "B4 (yes/no) · B5 − intermediate"), ("B", "B5 − provenance · B5 − authority"),
                         ("C", "B5 − RAG · B5 − ASK"), ("D", "B5 − ESCALATE · B5 with a second seed")):
        ms = (runs.get(letter) or {}).get("models") or []
        trows.append({"Run": letter, "Models": plan,
                      "Status": "✓ trained" if ms else "… training",
                      "Steps": " · ".join(f"{m.get('global_step')}" for m in ms) or "–",
                      "Final training loss": " · ".join(f"{m.get('train_loss'):.3f}" for m in ms
                                                       if m.get("train_loss") is not None) or "–",
                      "Hours": " · ".join(f"{(m.get('runtime_s') or 0) / 3600:.1f}" for m in ms) or "–"})
    st.dataframe(pd.DataFrame(trows), hide_index=True, width="stretch")
    st.caption("Lower training loss does not mean a better gate; the scoring run decides.")
    st.markdown("#### The run plan")
    C.cards([
        {"kicker": "Run 1 · done", "status": "ok", "title": "Baselines and the first trained gate",
         "body": "B1–B3 and B5 on the frozen test set (10–11 Nov)."},
        {"kicker": "GateExp and final design · done", "status": "ok", "title": "Layers around the model",
         "body": "GateExp (GX), then the final design (GX3) on dev, red-team, combinations and a live AgentDojo "
                 "run (11–12 Nov)."},
        {"kicker": "Final runs · now", "status": "info", "title": "B4, ablations, second seed",
         "body": "Trained in parallel on 13 Nov (runs A–D). Then one scoring run on dev, red-team and test, the "
                 "[[blind test set]], and confidence intervals."},
    ])

# ------------------------------------------------------------------ journey
with tabs[3]:
    st.markdown("#### How the project got here")
    events = [
        ("26 Oct", "Benchmark exported", "AgentDojo office and bank worlds: 760 scenarios and 23,602 published "
                                          "agent traces from 29 set-ups. The scenario split was fixed."),
        ("26–30 Oct", "Pipeline built", "Evidence builder, gates B1–B5, the question loop and the Kaggle "
                                         "notebooks. B0 measured: attacks succeed 8.3% of the time."),
        ("29 Oct", "First trained results", "B5 on 160 provisional cases: 87.5% correct, but 19% unsafe."),
        ("6–9 Nov", "Human labelling", "The team reviewed 2,000 cases. 1,497 were frozen into train, dev and test, "
                                        "split by family."),
        ("9 Nov", "Audit", "The pipeline was checked against the frozen data. Leaks and scoring problems were found "
                           "and fixed."),
        ("10 Nov", "Fixes and better retrieval", "New evidence, safety guards, and retrieval that finds 95% of the "
                                                  "key rules. A training fix made 2-epoch runs fit on a free T4 GPU."),
        ("10–11 Nov", "Run 1", "Smoke test, baselines B1–B3, and B5 trained and evaluated on the frozen test set."),
        ("11 Nov", "Code review and stress test", "A full code review, and 90 hand-made tricky cases that target "
                                                  "the weak spots."),
        ("11–12 Nov", "GateExp", "B5 retrained as B5 v2 and placed inside layers of facts, hard rules and "
                                 "after-checks; 61 new red-team attacks; a confirmation policy for new payees "
                                 "(25 cases relabelled). Test: 0% unsafe; dev: 2.7%."),
        ("12 Nov", "Final design", "B5 retrained again with a cost-matrix loss and factor-combination data "
                                   "(b5_v3_combo), inside the GateExp layers. Two code reviews fixed how approvals, "
                                   "untraced targets and amounts are handled. Dev 236/236, red-team 60/61, 216 "
                                   "combinations 215/216, with 0 unsafe on all three."),
        ("12 Nov", "Live AgentDojo run", "The whole agent with the final design in front of every risky action: 0 of "
                                         "120 attacks worked (10 without a gate), 50 of 142 tasks done (49 without)."),
        ("13 Nov", "Locked, final training", "Code locked as locked-v4. Four teammates trained B4, the six ablations "
                                             "and a second B5 seed in parallel (runs A–D). Test is held back for one "
                                             "final run; a blind test set is being written."),
    ]
    html = "".join(f'<div class="sg-step"><div class="ico" style="width:92px;font-size:.8rem;'
                   f'font-weight:700;color:#1c5cab;background:#eef4fd">{C.esc(d)}</div><div class="body">'
                   f'<div class="title">{C.esc(t)}</div><div class="sub">{C.esc(b)}</div></div></div>'
                   for d, t, b in events)
    C.show(f'<div class="sg-card">{html}</div>')

# ------------------------------------------------------------------ limits
with tabs[4]:
    st.markdown("#### What we know is not solved yet")
    st.markdown("A security project should say where it is weak. These come from the team's own audit and code "
                "review.")
    C.cards([
        {"kicker": "Open", "status": "warn", "title": "Quiet injections",
         "body": "An attack worded like a normal request, with no suspicious phrases, looks trusted when "
                 "provenance is only guessed."},
        {"kicker": "Open", "status": "warn", "title": "An extra recipient in a list",
         "body": "“Email David” turned into “email David and attacker@…” still counts as user-named, because one "
                 "address in the list came from the user."},
        {"kicker": "Fixed 12 Nov", "status": "ok", "title": "Unknown tools and odd amounts",
         "body": "An unknown tool now always goes through the gate, and amounts like “Send David 1800” or “5e3” are "
                 "read correctly. An amount that can't be read is refused instead of passing every limit."},
        {"kicker": "Handled in reporting", "status": "info", "title": "The scoring can reward asking",
         "body": "The simulated user always answers correctly, so asking everything looks great. That's why "
                 "'needless questions' is always reported next to 'unsafe'."},
        {"kicker": "Handled in reporting", "status": "info", "title": "Some rules saw test cases",
         "body": "Some guard rules and some GateExp rules were designed while looking at test failures. Their test "
                 "numbers are marked optimistic; dev and the red-team set are the fairer check."},
        {"kicker": "Open · reported both ways", "status": "warn", "title": "Two sets of labels",
         "body": "After the freeze the team relabelled some cases to its “confirm new payees and unstated amounts” "
                 "policy (8 dev cases differ for the final design). This site scores every gate against the frozen "
                 "labels and shows the team's own count next to it."},
        {"kicker": "Done 12 Nov", "status": "ok", "title": "The final design, live",
         "body": "In the live AgentDojo run, where provenance has to be guessed, the final design let 0 of 120 "
                 "attacks through. (For Run 1's B5, guessing provenance raised unsafe actions to 20%.)"},
        {"kicker": "Planned", "status": "info", "title": "Small test, one run",
         "body": "212 test cases in 21 families; the final design takes the test once. A second B5 seed was trained "
                 "to measure seed variance, and family-level confidence intervals come with the final statistics."},
    ], two=True)
