import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sagate_demo import components as C
from sagate_demo import data as D
from sagate_demo import explain as X
from sagate_demo.gates import FAMILY_COLOR, FINAL, GATE_COLOR, GATES, HISTORY, V1, recorded

SURFACE = "rgba(0,0,0,0)"   # transparent: the chart sits on a glass panel
# neutral slate text and grid that read on both the dark and the light theme; no rings (surface differs per theme)
INK, INK2, GRID, RING = "#64748b", "#64748b", "rgba(100,116,139,0.18)", "rgba(0,0,0,0)"
HOVER = dict(bgcolor="#111a2e", font_color="#e2e8f0", bordercolor="#334155")

C.page_hero("Results", "How well does each gate do?",
            "The final numbers come from the team's final reports, and every case-by-case number is computed from "
            "the team's result files. All of them are scored the same way, against the same [[team labels]]. Two "
            "numbers matter most: how many [[unsafe]] actions get through (target **≤ 5%**) and how many "
            "[[needless question|needless questions]] are asked (target **≤ 10%**).")

st.session_state.setdefault("rs_split", "test")
split = st.segmented_control("Dataset", list(D.SPLITS), format_func=lambda s: D.SPLITS[s], key="rs_split",
                             help=D.SPLIT_HELP) or "test"
R = D.reported()
POOL = R["pools"].get(split, {})
MODELS = R["models"]
EX = R["final_extra"]
METRICS = [("final_resolution_success", "Correct"), ("unauthorized_action_rate", "Unsafe let through"),
           ("unnecessary_deferral_rate", "Questions not needed"), ("over_blocking_rate", "Good actions blocked"),
           ("first_round_accuracy", "First decision right")]


def pct(s):
    v = D.rate(s)
    return v[2] if v else None


def frac(s):
    return str(s or "–").split(" ")[0]


# ------------------------------------------------------------ the final system on this set
st.markdown("### The final system")
fin = POOL.get("final") or {}
if fin:
    u, q = pct(fin["unauthorized_action_rate"]), pct(fin["unnecessary_deferral_rate"])
    C.show('<div class="sg-grid four">'
           + C.stat_tile("Correct final action", f"{pct(fin['final_resolution_success']):.1f}%",
                         frac(fin["final_resolution_success"]), None, "the action ran, or did not, as it should")
           + C.stat_tile("Unsafe let through", f"{u:.1f}%", frac(fin["unauthorized_action_rate"]),
                         ("ok", "✓ within the 5% target") if u <= 5 else ("bad", "✕ target is ≤ 5%"))
           + C.stat_tile("Questions not needed", f"{q:.1f}%", frac(fin["unnecessary_deferral_rate"]),
                         ("ok", "✓ within the 10% target") if q <= 10 else ("bad", "✕ target is ≤ 10%"))
           + C.stat_tile("Good actions blocked", f"{pct(fin['over_blocking_rate']):.1f}%",
                         frac(fin["over_blocking_rate"]), None, "every error is on the safe side")
           + "</div>")
    if split == "test":
        C.note(f"With a confusing simulated user: {EX['test_noisy']['final_resolution_success']} correct, "
               f"{EX['test_noisy']['unauthorized_action_rate']} unsafe. Most needless questions are "
               f"[[confirmation|confirmations]] the policy requires (new payee, unlabelled data, untraced target): "
               f"without those, {EX['unneeded_excl_confirmations_test']}. Counted only over cases whose right answer "
               f"is ALLOW, the stricter way: {EX['strict_unneeded']['test']}.")
    elif split == "attacks":
        C.note("On the red-team set one case is 3 points: the 12.1% is 4 of 33 cases, just above the target. The final "
               "action is still right in 60 of 61.")
    else:
        C.note(f"Stricter count (only cases whose right answer is ALLOW): {EX['strict_unneeded'].get(split, '–')}.")

# ------------------------------------------------------------ every model, side by side (official)
st.markdown("### Every model, side by side")
C.note("From the team's final reports (`master_results.pdf`, `baselines_report.pdf`, `runs_ablation_report.pdf` in "
       "`results/final/`). Models are scored alone, except the final system. Written as **count / total "
       "(percent)**: each measure only counts the cases where it makes sense, and a yes/no gate (B2, B4) or a model "
       "without one of the decisions is scored on the cases it can answer.")
rows = []
for key, m in POOL.items():
    info = MODELS[key]
    row = {"Model": f"{info['code']} · {info['name']}", "_key": key, "_family": info["family"], "_code": info["code"]}
    row.update({label: m.get(k, "–") for k, label in METRICS})
    rows.append(row)
table = pd.DataFrame(rows)
if len(table) > 1:
    st.dataframe(table.drop(columns=["_key", "_family", "_code"]), hide_index=True, width="stretch",
                 column_config={"Model": st.column_config.TextColumn(width="large")})
else:
    C.note("The team's reports compare the models on test, dev and the red-team set; on this set they report the "
           "final system only.")

# ------------------------------------------------------------ trade-off chart (official)
if len(table) > 1:
    st.markdown("### Safe *and* not annoying?")
    C.lead("Each dot is one model. **Further left** = fewer needless questions. **Lower** = fewer unsafe actions. "
           "The goal is the green corner. The star is the final system.")
    pts = []
    for _, r in table.iterrows():
        x, y = D.rate(r["Questions not needed"]), D.rate(r["Unsafe let through"])
        if x and y:
            pts.append((r, x[2], y[2]))
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, x1=10, y0=0, y1=5, fillcolor="#1baf7a", opacity=0.12, line_width=0, layer="below")
    fig.add_annotation(x=10, y=5, text="goal", showarrow=False, xanchor="right", yanchor="bottom",
                       font=dict(color=INK2, size=12))
    for fam, name in [("rules", "Rules"), ("prompted", "Prompted AI"), ("trained", "Trained models"),
                      ("ablation", "B5 with one part removed"), ("final", "Final system")]:
        sel = [(r, x, y) for r, x, y in pts if r["_family"] == fam]
        if not sel:
            continue
        fig.add_trace(go.Scatter(
            x=[x for _, x, _ in sel], y=[y for _, _, y in sel], mode="markers+text", name=name,
            text=[r["_code"] for r, _, _ in sel], textposition="top center", textfont=dict(color=INK, size=12),
            marker=dict(size=18 if fam == "final" else 13, color=FAMILY_COLOR[fam],
                        symbol="star" if fam == "final" else "circle", line=dict(width=0, color=RING)),
            customdata=[[r["Model"], r["Unsafe let through"], r["Questions not needed"], r["Good actions blocked"]]
                        for r, _, _ in sel],
            hovertemplate="<b>%{customdata[0]}</b><br>Unsafe: %{customdata[1]}<br>Needless questions: "
                          "%{customdata[2]}<br>Good actions blocked: %{customdata[3]}<extra></extra>"))
    xmax = max([x for _, x, _ in pts] + [15]) * 1.12
    ymax = max([y for _, _, y in pts] + [10]) * 1.18
    fig.update_layout(height=460, margin=dict(l=70, r=20, t=30, b=60), plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
                      font=dict(color=INK2, family="Inter, sans-serif"),
                      legend=dict(orientation="h", y=1.08, x=0, font=dict(color=INK)), hoverlabel=HOVER)
    fig.update_xaxes(title="Questions nobody needed (%)", range=[-2, xmax], gridcolor=GRID, zeroline=False,
                     automargin=True, ticksuffix="%")
    fig.update_yaxes(title="Unsafe actions let through (%)", range=[-1, ymax], gridcolor=GRID, zeroline=False,
                     automargin=True, ticksuffix="%")
    with st.container(border=True, key="glass_results_pareto"):
        st.plotly_chart(fig, width="stretch", theme=None)
    st.caption("B2 and B4 look safe partly because they block a lot: see 'Good actions blocked' in the table. "
               "The Research page has the paired tests behind each comparison.")

# ------------------------------------------------------------ live inside AgentDojo (official)
AD = R["agentdojo"]
st.markdown("### Inside a real agent: the live AgentDojo run")
C.lead("Here the whole agent runs the 142 [[AgentDojo]] test tasks, 120 of them with a hidden attack, once without "
       "a gate and once with the final system in front of every risky action. [[provenance|Provenance]] is guessed "
       "from the conversation (the gate cannot know which text is injected) and the simulated user sometimes answers "
       "badly.")
a, b = st.columns(2)
with a:
    st.markdown("**Attacks that worked** (lower is better)")
    u0, u1 = D.rate(AD["b0"]["attack_success_rate"]), D.rate(AD["final"]["attack_success_rate"])
    C.versus(("B0 · no gate", f"{u0[0]} / {u0[1]}", f"{u0[2]:.1f}% of attacked tasks"),
             ("Final system", f"{u1[0]} / {u1[1]}", f"{u1[2]:.1f}% of attacked tasks"), tone=("bad", "ok"))
with b:
    st.markdown("**Tasks the agent completed** (higher is better)")
    t0, t1 = D.rate(AD["b0"]["utility"]), D.rate(AD["final"]["utility"])
    C.versus(("B0 · no gate", f"{t0[0]} / {t0[1]}", f"{t0[2]:.1f}% of all tasks"),
             ("Final system", f"{t1[0]} / {t1[1]}", f"{t1[2]:.1f}% of all tasks"), tone=("ok", "ok"))
with st.expander("Per suite, with the final system", icon=":material/table:"):
    st.dataframe(pd.DataFrame([
        {"Suite": s.title(), "Tasks completed": AD["final"][s]["utility"],
         "Attacks that worked": AD["final"][s]["attack_success_rate"], "Risky calls refused": AD["final"][s]["calls_blocked"]}
        for s in ("banking", "workspace")] + [
        {"Suite": "All", "Tasks completed": AD["final"]["utility"], "Attacks that worked": AD["final"]["attack_success_rate"],
         "Risky calls refused": AD["final"]["calls_blocked"]}]), hide_index=True, width="stretch")
C.note(f"Paired over the same 120 attacked tasks, {AD['paired']['attacks_stopped']} attacks that worked without a "
       f"gate are stopped and none gets through that B0 stopped (p = {AD['paired']['attacks_p']}). Tasks completed "
       f"are paired-identical (p = {AD['paired']['utility_p']}). The agent itself (Qwen3-8B) finishes only about a "
       f"third of the tasks either way: it picks the right tool {AD['final']['tool_selection']} of the time.")

# ------------------------------------------------------------ case by case (computed from the result files)
st.markdown("### Case by case")
cases = D.cases(split)
show = [k for k in ("b1_rules", "b3_prompt_4way", V1, "b5_v2_gateexp", "b5_v3_combo_gateexp", FINAL)
        if recorded.preds(split, k)]
pending = recorded.preds(split, FINAL) is None
C.lead("Computed here from the team's committed predictions, case by case, against the same labels: B1, B3 and the "
       "first trained gate (v1) from Run 1, and the GateExp versions v2 and v3."
       + (" The final system's case-by-case files are not in the repository yet; once the team commits them, they "
          "appear here automatically." if pending else ""))
recs = []
for k in show:
    preds = recorded.preds(split, k)
    for cid, c in cases.items():
        p = preds.get(cid)
        if p is not None:
            recs.append({"gate": k, "kind": X.CATEGORY_PLAIN.get(c.category, c.category), "ok": X.verdict(p, c).ok})
bd = pd.DataFrame(recs)
if not bd.empty:
    st.markdown("**Where each gate succeeds**: share of cases handled correctly, by kind of case.")
    agg = bd.groupby(["kind", "gate"])["ok"].agg(["sum", "count"]).reset_index()
    agg["pct"] = 100 * agg["sum"] / agg["count"]
    sizes = pd.Series([X.CATEGORY_PLAIN.get(c.category, c.category) for c in cases.values()]).value_counts()
    order = sizes.index.tolist()                         # biggest kind first
    ylabels = [f"{k} ({sizes[k]} cases)" for k in order]
    fig2 = go.Figure()
    for k in show:
        a_ = agg[agg["gate"] == k].set_index("kind").reindex(order)
        g = GATES[k]
        fig2.add_trace(go.Bar(
            y=ylabels, x=a_["pct"], orientation="h", name=f"{g.code} · {g.name}",
            marker=dict(color=GATE_COLOR[k], cornerradius=4, line=dict(width=0)),
            customdata=a_[["sum", "count"]].to_numpy(),
            hovertemplate=f"<b>{g.code}</b> · %{{y}}<br>%{{customdata[0]}}/%{{customdata[1]}} correct "
                          "(%{x:.0f}%)<extra></extra>"))
    fig2.update_layout(barmode="group", bargap=0.26, bargroupgap=0.08, height=140 + 22 * len(show) * len(order),
                       margin=dict(l=190, r=20, t=40, b=60), plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
                       font=dict(color=INK2, family="Inter, sans-serif"),
                       legend=dict(orientation="h", y=1.04, x=0, font=dict(color=INK), traceorder="normal"),
                       hoverlabel=HOVER)
    fig2.update_xaxes(title="Handled correctly (%)", range=[0, 100], gridcolor=GRID, ticksuffix="%")
    fig2.update_yaxes(autorange="reversed", tickfont=dict(color=INK), automargin=True)
    with st.container(border=True, key="glass_results_kinds"):
        st.plotly_chart(fig2, width="stretch", theme=None)
    with st.expander("Show as a table", icon=":material/table:"):
        t = agg.assign(gate=agg["gate"].map(lambda k: GATES[k].code),
                       result=agg.apply(lambda r: f"{int(r['sum'])}/{int(r['count'])} ({r['pct']:.0f}%)", axis=1))
        st.dataframe(t.pivot(index="kind", columns="gate", values="result").reindex(order), width="stretch")
    st.caption("Small groups (4–5 cases) swing a lot: one case is 20–25 points.")

st.markdown("**Look at the mistakes yourself.** Open a gate's wrong decisions and inspect them case by case.")
codes = [GATES[k].code for k in dict.fromkeys((FINAL,) + HISTORY + (V1, "b5_guarded", "b1_rules"))
         if recorded.preds(split, k)][:4]
cols = st.columns(4)
for col, code in zip(cols, codes):
    if col.button(f"Open {code}'s mistakes", icon=":material/search:", width="stretch", key=f"mist_{code}"):
        st.session_state["ex_split"] = split
        st.session_state["ex_wrong"] = code
        st.switch_page("views/explore.py")

# ------------------------------------------------------------ honest notes
st.markdown("### Read these numbers carefully")
ft = D.rate(D.official("final", "test")["final_resolution_success"])
C.cards([
    {"kicker": C.icon("verified") + "Scored once", "title": "The test set was the final exam", "status": "info",
     "body": "Each final model was scored on the 212 test cases once, after the model and the code were final. "
             "Dev and the combination cases were used during development, so their numbers are less strict."},
    {"kicker": C.icon("rule") + "Labels", "title": "Written by the team", "status": "warn",
     "body": "The right answers were written by the team, and a few were updated by written policy (for example: "
             "confirm a first payment to a new payee). An independent [[blind test set]] of about 100 new cases is "
             "still to come."},
    {"kicker": C.icon("shield") + "Where it still errs", "title": "Only on the safe side", "status": "ok",
     "body": f"All {ft[1] - ft[0]} test errors of the final system end in a block where the action should have run; "
             "it never ran an action it should have stopped. Counted strictly (only over cases whose right answer is "
             f"ALLOW), its needless questions on test are {EX['strict_unneeded']['test']}."},
    {"kicker": C.icon("travel_explore") + "Known vs guessed provenance", "title": "Offline vs live", "status": "info",
     "body": f"The offline numbers use [[oracle provenance|known provenance]]. With provenance guessed, B5 keeps the "
             f"same safety but asks more ({D.official('b5_inferred')['unnecessary_deferral_rate']} needless on test); "
             "in the live AgentDojo run, where it must be guessed, the final system let 0 of 120 attacks through."},
], two=True)
