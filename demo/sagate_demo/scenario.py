"""One case, told as a story in six steps. Two ways to read it:

- guided: one step at a time with Back / Next (for presenting);
- full: every step on one page (for reading or exploring).
"""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from . import components as C
from . import data as D
from . import explain as X
from .gates import GATES, NEWEST, OURS, LiveSettings, live, recorded

STEPS = ["The request", "The agent acts", "The evidence", "The decisions", "The right answer", "Try it live"]


def _k(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- the six steps

def step_request(split, case_id, meta):
    c = D.cases(split)[case_id]
    gi = D.gate_view(split, case_id)
    C.user_bubble(gi.user.get("prompt", ""))
    if meta:
        st.markdown(meta["story"])
        C.callout("catch", "The catch:", meta["catch"])
    else:
        st.caption(f"Kind of case: {X.CATEGORY_PLAIN.get(c.category, c.category)} · world: {c.input.suite}")


def step_agent(split, case_id, meta):
    gi = D.gate_view(split, case_id)
    st.markdown("The AI agent works on the request. Reading is harmless, so it passes straight through. The moment "
                "it wants to **change** something, the gate stops it.")
    C.agent_steps(gi)


def step_evidence(split, case_id, meta):
    c = D.cases(split)[case_id]
    gi = D.gate_view(split, case_id)
    st.markdown("Before deciding, the gate collects four kinds of facts. Every gate, rules or AI, gets **exactly the "
                "same facts**, which keeps the comparison fair.")
    C.evidence_cards(X.evidence(gi, c))
    if gi.untrusted_content:
        st.markdown("**What the agent read** (the gate treats this only as data):")
        C.untrusted(gi)
    with st.expander("Technical details (the raw evidence)", icon=":material/data_object:"):
        technical(split, case_id)


def step_decisions(split, case_id, meta):
    c = D.cases(split)[case_id]
    k = _k(split, case_id)
    has_noisy = bool((c.user_response or {}).get("noisy"))
    left, right = st.columns([3, 2])
    with left:
        C.show('<p class="sg-lead" style="font-size:.95rem">' + C.md(
            "Each gate's first decision, any question and answer, and the final outcome. The highlighted row is the "
            "**newest design ([[GateExp]])**; B5 is the Run 1 version of our trained gate.") + "</p>")
    noisy = right.toggle("Use the confusing user reply", key=f"noisy{k}", disabled=not has_noisy,
                         help="15% of cases also have a deliberately confusing reply, to test robustness. "
                              "Only those cases can use it.")
    runs = recorded.all(split, case_id, noisy)
    C.comparison(runs, c)
    gx = next((r for r in runs if r.gate.key == NEWEST and r.trace is not None), None)
    if gx is not None:
        with st.container(border=True):
            st.markdown("**How the newest gate decided, layer by layer**")
            st.caption("GateExp computes facts, applies hard rules, asks the trained model only if no rule "
                       "decided, then runs checks that can only make the answer stricter. The highlighted layer "
                       "made the decision. Hover a rule name to see what it means.")
            for r in gx.trace["rounds"]:
                if len(gx.trace["rounds"]) > 1:
                    st.markdown(f"Round {r['round'] + 1}" + (" (after the answer)" if r["round"] else ""))
                C.show(C.gx_path(r["output"]))
    scored = [r for r in runs if r.trace is not None]
    with st.expander("Look closer at one gate: how sure was it?", icon=":material/zoom_in:"):
        pick = st.selectbox("Gate", [r.gate.key for r in scored], key=f"pick{k}",
                            index=[r.gate.key for r in scored].index(OURS) if any(r.gate.key == OURS for r in scored)
                            else 0, format_func=lambda key: f"{GATES[key].code} · {GATES[key].name}")
        run = next(r for r in scored if r.gate.key == pick)
        gate_detail(run, c)


def gate_detail(run, c):
    first = run.trace["rounds"][0]["output"]
    a, b = st.columns(2)
    with a:
        st.markdown("**First decision**")
        C.show(C.chip(first["decision"]))
        me, ra = first.get("missing_evidence"), first.get("required_authority")
        if me and me != "none":
            st.markdown(f"What it thought was missing: **{me.replace('_', ' ')}**"
                        + (f" — it would ask *“{X.QUESTION[me]}”*" if me in X.QUESTION else ""))
        if ra and ra not in ("none",):
            st.markdown(f"Who it thought must decide: **{X.ROLE_PLAIN.get(ra, ra)}**")
        if first.get("guard"):
            st.markdown(f":material/shield: A safety guard changed the model's answer: "
                        f"{X.GUARD_PLAIN.get(first['guard'], first['guard'])}.")
    with b:
        probs = X.probabilities(run.trace)
        if probs:
            st.markdown("**How sure the model was** (first decision)")
            C.show(C.prob_bars(probs))
        elif run.gate.family == "rules":
            st.markdown("**Rules have no probabilities.** They either fire or they don't.")
        else:
            st.markdown("**A hard rule decided before the model was asked**, so there are no model scores for "
                        "this round.")
    v = X.verdict(run.trace, c)
    getattr(st, v.tone)(f"**{v.label}.** {v.why}")


def step_answer(split, case_id, meta):
    c = D.cases(split)[case_id]
    parts = [f"First decision {C.chip(c.gold_decision)}"]
    if c.gold_missing_evidence and c.gold_missing_evidence != "none":
        parts.append(f"missing: <b>{C.esc(c.gold_missing_evidence.replace('_', ' '))}</b>")
    if c.gold_required_authority and c.gold_required_authority != "none":
        parts.append(f"who decides: <b>{C.esc(X.ROLE_PLAIN.get(c.gold_required_authority))}</b>")
    parts.append(f"final action {C.chip(c.gold_final_action)}")
    C.show('<div class="sg-card"><div class="sg-kicker">Decided by the human labellers</div>'
           f'<div class="sg-flow" style="gap:12px">{" · ".join(parts)}</div></div>')
    if meta:
        C.callout("right", "Why:", meta["right"])
        C.callout("lesson", "What this shows:", meta["lesson"])
    rl = D.relabels().get(case_id)
    if rl:
        what = "; ".join(f"{k.replace('gold_', '').replace('_', ' ')}: {a} → {b}" for k, (a, b) in rl.items())
        C.callout("new", "Note:", f"on the [[GateExp]] branch this case was relabelled ({what}). The new policy "
                                  "asks the user to confirm before a first payment to a new payee, or an amount "
                                  "the user never stated. This site scores every gate against the team's "
                                  "[[frozen labels]].")
    if c.gold_clause_ids:
        book = D.handbook()
        st.markdown("**The handbook rules that apply**")
        for cid in c.gold_clause_ids:
            cl = book.get(cid, {})
            st.markdown(f"- `{cid}` **{cl.get('title', '')}**: {cl.get('text', '')}")


def step_live(split, case_id, meta):
    c = D.cases(split)[case_id]
    k = _k(split, case_id)
    st.markdown("Switch evidence on or off and the **rules gate (B1) runs again, live**, with the project's real "
                "code. No AI and no GPU are needed. The defaults give exactly the recorded result.")
    if meta and meta.get("try"):
        C.callout("lesson", "💡 Try this:", meta["try"])
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        prov = st.segmented_control("Provenance: where things came from", ["known", "guessed", "hidden"],
                                    default="known", key=f"prov{k}",
                                    help="known = the benchmark tells us what was injected (best case) · guessed = "
                                         "string matching, like a real system · hidden = no provenance at all")
        auth = st.toggle("Authority: who may approve", True, key=f"auth{k}")
        sens = st.toggle("Sensitivity labels", True, key=f"sens{k}")
        rag = st.toggle("Handbook rules (RAG)", True, key=f"rag{k}")
        guards = st.toggle("Safety guards", False, key=f"grd{k}")
        noisy = st.toggle("Confusing user reply", False, key=f"lnoisy{k}",
                          disabled=not (c.user_response or {}).get("noisy"),
                          help="Only some cases have a confusing reply variant.")
    s = LiveSettings({"known": "oracle", "guessed": "inferred", "hidden": "none"}[prov or "known"], auth, sens, rag,
                     guards, noisy)
    run = live.run(split, case_id, s)
    v = X.verdict(run.trace, c)
    with right:
        st.markdown("**B1 rules · live result**")
        C.show(f'<div class="sg-card {dict(success="ok", warning="warn", error="bad")[v.tone]}">'
               f'{C.flow(run.trace)}<div style="margin-top:10px">{C.verdict(v)}</div>'
               f'<p style="margin-top:6px">{C.esc(v.why)}</p></div>')
        if s.is_default:
            same = live.matches_recorded(split, case_id)
            if same:
                st.caption(":material/verified: Same as the recorded Run 1 result.")
            elif same is False:
                st.caption(":material/error: Differs from the recorded Run 1 result.")
        else:
            base = X.verdict(live.run(split, case_id).trace, c)
            if base.ok != v.ok:
                st.caption(":material/compare_arrows: Your switches changed the outcome: with all evidence on, "
                           f"B1 is **{base.short.lower()}**.")
            else:
                st.caption(":material/compare_arrows: Same outcome as with all evidence on.")


RENDER = [step_request, step_agent, step_evidence, step_decisions, step_answer, step_live]


# ---------------------------------------------------------------- technical view

def technical(split, case_id):
    gi = D.gate_view(split, case_id)
    rows = []
    args = gi.proposed_call.get("args") or {}
    for r in gi.provenance or []:
        if r.get("kind") == "call":
            rows.append({"ID": r["id"], "What": "the whole action", "Value": f"origin: {r.get('instruction_origin')}",
                         "Trust": r.get("trust")})
        else:
            rows.append({"ID": r["id"], "What": f"argument {r.get('arg')}",
                         "Value": str(r.get("value", args.get(r.get("arg"))))[:80], "Trust": r.get("trust")})
    st.markdown("**Provenance records**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown("**Authority and sensitivity**")
    st.json({"authority": gi.authority, "sensitivity": gi.sensitivity}, expanded=False)
    if gi.checks:
        st.markdown("**Computed checks**")
        st.dataframe(pd.DataFrame([{"Check": X.CHECK_PLAIN.get(a, a), "Result": str(b)} for a, b in gi.checks.items()]),
                     hide_index=True, width="stretch")
    st.markdown("**The 8 rules the retriever picked** (⭐ = marked relevant by the labellers)")
    gold = set(D.cases(split)[case_id].gold_clause_ids or [])
    for i, cl in enumerate(gi.policy_clauses or [], 1):
        st.markdown(f"{i}. `{cl['id']}` {'⭐ ' if cl['id'] in gold else ''}**{cl['title']}**: {cl['text']}")


# ---------------------------------------------------------------- layouts

def header(split, case_id, meta, score: bool = True):
    c = D.cases(split)[case_id]
    title = meta["title"] if meta else X.CATEGORY_PLAIN.get(c.category, c.category)
    kind = meta["kind"] if meta else X.CATEGORY_PLAIN.get(c.category, c.category)
    st.markdown(f"## {title}")
    C.show(C.tag(kind, "violet") + C.tag(c.input.suite) + C.tag(f"{split} set") +
           f'<span class="sg-tag" style="font-family:monospace;font-weight:500">{C.esc(case_id)}</span>')
    if score:
        C.scoreboard(recorded.all(split, case_id), c)


def guided(split, case_id, meta=None):
    """One step at a time, with Back / Next."""
    k = _k("guided", split, case_id)
    key = f"step{k}"
    if key not in st.session_state:
        st.session_state[key] = 0

    def go(delta):
        st.session_state[key] = min(max((st.session_state.get(key) or 0) + delta, 0), len(STEPS) - 1)

    i_now = st.session_state.get(key) or 0
    header(split, case_id, meta, score=i_now >= 3)
    st.segmented_control("Step", list(range(len(STEPS))), key=key, label_visibility="collapsed",
                         format_func=lambda i: f"{i + 1}. {STEPS[i]}")
    i = st.session_state.get(key)
    if i is None:          # clicking the selected step again deselects it; stay on step 1
        i = 0
    st.progress((i + 1) / len(STEPS))
    with st.container(border=True):
        st.markdown(f"### {i + 1} · {STEPS[i]}")
        RENDER[i](split, case_id, meta)
    b, _, n = st.columns([1, 3, 1])
    b.button("← Back", key=f"back{k}", on_click=go, args=(-1,), disabled=i == 0, width="stretch")
    n.button("Next →" if i < len(STEPS) - 1 else "Done", key=f"next{k}", on_click=go, args=(1,),
             disabled=i == len(STEPS) - 1, type="primary", width="stretch")


def full(split, case_id, meta=None):
    """Every step on one page."""
    header(split, case_id, meta)
    for i, (name, fn) in enumerate(zip(STEPS, RENDER)):
        st.markdown(f"### {i + 1} · {name}")
        fn(split, case_id, meta)
