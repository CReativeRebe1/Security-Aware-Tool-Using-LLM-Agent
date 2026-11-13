"""Small HTML components rendered with st.html. Every piece of data text goes through `esc` (or `md`, which
escapes and then turns `code` spans into <code>), so nothing from a case file can inject markup."""

from __future__ import annotations

import base64
import html
import json
import re

import streamlit as st

from . import data as D
from . import explain as X
from .gates import NEWEST, PREV_GX, GateRun


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def md(s) -> str:
    """Escape, then render `code`, **bold** and *italic*."""
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s))
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<i>\1</i>", out)
    return re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: term(m.group(2) or m.group(1), m.group(1)), out)


def term(text: str, key: str | None = None) -> str:
    """A word with a hover explanation from the glossary (text is already escaped when called from md)."""
    tip = X.GLOSSARY.get((key or text).strip().lower())
    return f'<span class="sg-term" data-tip="{esc(tip)}">{text}</span>' if tip else text


def show(markup: str) -> None:
    st.html(markup)


def icon(name: str, cls: str = "") -> str:
    """A line icon from Material Symbols (the icon font Streamlit already loads for its own menus)."""
    return f'<span class="sg-mi {cls}" aria-hidden="true">{esc(name)}</span>'


REPO_URL = "https://github.com/CReativeRebe1/Security-Aware-Tool-Using-LLM-Agent"
REPORT_URL = REPO_URL + "/blob/main/docs/report/gate_report.pdf"


THEME_PROBE = """<!doctype html><html><body style="margin:0"><script>
(function () {
  // Streamlit does not expose the visitor's theme to CSS, but it colours the app text from it: light text means the
  // dark theme. Mirror that onto <html data-sg-theme> of the app page, so style.css / light.css can follow it.
  var P; try { P = window.parent.document; } catch (e) { return; }
  function sync() {
    var app = P.querySelector('.stApp'); if (!app) return;
    var m = getComputedStyle(app).color.match(/[0-9.]+/g); if (!m) return;
    var lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
    var t = lum > 0.5 ? 'dark' : 'light';
    if (P.documentElement.getAttribute('data-sg-theme') !== t) P.documentElement.setAttribute('data-sg-theme', t);
  }
  sync(); setInterval(sync, 300);
})();
</script></body></html>"""


def theme_probe() -> None:
    """An invisible helper frame that keeps <html data-sg-theme="light|dark"> in step with the visitor's theme."""
    with st.container(key="sg_theme_probe"):
        st.iframe(THEME_PROBE, height=1, tab_index=-1, alt="")


def load_css() -> None:
    """Dark theme (style.css) plus the light theme's overrides (light.css, active when <html data-sg-theme="light">)."""
    st.html(f"<style>{D.asset('style.css')}\n{D.asset('light.css')}</style>")


# ---------------------------------------------------------------- atoms

CHIP_ICON = {"ALLOW": "check", "BLOCK": "block", "ASK_USER": "help", "ESCALATE": "arrow_upward"}


def chip(decision: str | None) -> str:
    if not decision:
        return '<span class="sg-chip NONE">—</span>'
    return f'<span class="sg-chip {esc(decision)}">{icon(CHIP_ICON.get(decision, "circle"))}{esc(decision)}</span>'


def tag(text: str, cls: str = "") -> str:
    return f'<span class="sg-tag {cls}">{esc(text)}</span>'


def verdict(v: X.Verdict | None) -> str:
    if v is None:
        return '<span class="sg-verdict none">not scored</span>'
    icon = {"success": "✓", "warning": "!", "error": "✕"}[v.tone]
    return f'<span class="sg-verdict {v.tone}">{icon} {esc(v.short)}</span>'


def _img(name: str) -> str:
    """st.html strips inline <svg>; an <img> with a data URL survives the sanitizer."""
    return "data:image/svg+xml;base64," + base64.b64encode(D.asset(name).encode()).decode()


TEAM = ["Prabhash Padhan", "Rinkesh Verma", "Shubham Kumar Sunny", "Yogendra Patel"]
COURSE = "CL3410 · Language Models and Agents · IIIT Hyderabad"


def initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + parts[-1][0]).upper()


def avatar(name: str, i: int) -> str:
    return f'<span class="sg-av c{i % 4 + 1}" title="{esc(name)}">{esc(initials(name))}</span>'


def splash() -> None:
    """Opening intro, shown once per visit: logo, project name, course and the team, then it fades into the site."""
    team = "".join(f"<span><b>{esc(initials(n))}</b>{esc(n)}</span>" for n in TEAM)
    show(f'<div class="sg-splash" aria-hidden="true"><div class="sg-splash-inner">'
         f'<img class="sg-splash-logo" alt="" src="{_img("shield.svg")}">'
         f'<div class="sg-splash-title">SA-Gate</div>'
         f'<div class="sg-splash-sub">A security gate for tool-using AI agents</div>'
         f'<div class="sg-splash-course">{esc(COURSE)}</div>'
         f'<div class="sg-splash-by">Made by</div><div class="sg-splash-team">{team}</div>'
         f'<div class="sg-splash-bar"><i></i></div></div></div>')


def emblem() -> str:
    """The home banner's art: a glowing shield in rotating rings, the four decisions floating around it."""
    decs = [("d1", "ALLOW", "check"), ("d2", "BLOCK", "block"), ("d3", "ASK_USER", "help"), ("d4", "ESCALATE", "arrow_upward")]
    chips = "".join(f'<span class="dec {c}">{icon(i)}{esc(d)}</span>' for c, d, i in decs)
    return (f'<div class="sg-emblem"><div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div>'
            f'<div class="core"><img alt="" src="{_img("shield.svg")}"></div>{chips}</div>')


def hero(eyebrow: str, title: str, text: str, art: str | None = None, highlight: str | None = None) -> None:
    """Home banner. A title like 'SA-Gate: a security gate for AI assistants' becomes a big wordmark plus a line."""
    pic = ""
    if art == "emblem":
        pic = f'<div class="sg-hero-art">{emblem()}</div>'
    elif art:
        pic = f'<div class="sg-hero-art"><img alt="" src="{_img(art)}"></div>'
    name, _, line = title.partition(": ")
    line = esc(line[:1].upper() + line[1:]) if line else ""
    if highlight and line and esc(highlight) in line:
        line = line.replace(esc(highlight), f'<span class="sg-grad">{esc(highlight)}</span>', 1)
    head = f'<div class="sg-wordmark">{esc(name)}</div><h1>{line}</h1>' if line else f'<h1>{esc(title)}</h1>'
    made = (f'<div class="sg-made"><div class="sg-avs">{"".join(avatar(n, i) for i, n in enumerate(TEAM))}</div>'
            f'<div class="sg-made-txt">Made by<b>{" · ".join(esc(n) for n in TEAM)}</b></div></div>')
    show(f'<div class="sg-hero{" with-art" if art else ""}"><div class="sg-hero-copy"><div class="sg-eyebrow">'
         f'{esc(eyebrow)}</div>{head}<p>{esc(text)}</p>{made}</div>{pic}</div>')


def heading(kicker: str, title: str, sub: str = "") -> str:
    """A section heading as HTML: small coloured kicker, big title, optional grey line."""
    s = f'<p class="sg-sub">{md(sub)}</p>' if sub else ""
    return f'<div class="sg-kicker-lg">{esc(kicker)}</div><div class="sg-h2">{esc(title)}</div>{s}'


def team_section() -> None:
    cards = "".join(f'<div class="sg-member">{avatar(n, i)}<b>{esc(n)}</b><span>CL3410 · IIIT Hyderabad</span></div>'
                    for i, n in enumerate(TEAM))
    show(f'<div class="sg-team">{cards}</div>')


def page_hero(eyebrow: str, title: str, text: str) -> None:
    """The banner at the top of every page: what this page is and what you can do here."""
    show(f'<div class="sg-page-hero"><div class="sg-eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1>'
         f'<p>{md(text)}</p></div>')


def versus(left: tuple[str, str, str], right: tuple[str, str, str], tone=("bad", "ok")) -> None:
    """Before/after: (kicker, big value, caption) on each side."""
    cards = [f'<div class="sg-card {t}"><div class="sg-kicker">{esc(k)}</div><div class="big">{esc(v)}</div>'
             f'<p>{md(c)}</p></div>' for (k, v, c), t in zip((left, right), tone)]
    show(f'<div class="sg-vs">{cards[0]}<div class="arrow">→</div>{cards[1]}</div>')


def gx_path(output: dict) -> str:
    """GateExp's layers for one round: facts -> rules before the model -> the model -> checks after it."""
    tr = output.get("trace") or {}
    facts = tr.get("facts") or {}
    steps = tr.get("steps") or []
    model = tr.get("model")
    pre = [s for s in steps if s["rule"] in X.GX_PRE]
    post = [s for s in steps if s["rule"] not in X.GX_PRE]
    pre_fired = next((s["rule"] for s in pre if s.get("fired")), None)
    post_fired = [s["rule"] for s in post if s.get("fired")]
    lbl = lambda k: X.FACT_PLAIN.get(k, k) + ("" if X.FACT_PLAIN.get(k, k).endswith("?") else ":")
    f_html = "".join(f'<span class="sg-fact">{esc(lbl(k))} <b>{esc(X.fact_value(k, v))}</b></span>'
                     for k, v in facts.items() if k in X.FACT_PLAIN) or '<span class="sg-fact">—</span>'
    rules = lambda ss: "".join(f'<span class="sg-rule {"fired" if s.get("fired") else ""}" title="'
                               f'{esc(X.GX_RULE_PLAIN.get(s["rule"], s["rule"]))}">{esc(s["rule"])}</span>'
                               for s in ss)
    if model:
        m_html = (f'{chip(model.get("decision"))}<span class="sg-fact" style="margin-top:6px">'
                  f'sure it may run: <b>{(model.get("p_allow") or 0):.0%}</b></span>')
    else:
        m_html = '<span class="sg-fact">Not asked: a hard rule already decided.</span>'
    why = ""
    if pre_fired:
        why = X.GX_RULE_PLAIN.get(pre_fired, pre_fired)
    elif post_fired:
        why = X.GX_RULE_PLAIN.get(post_fired[0], post_fired[0])
    layers = [
        ("1 · Facts", f_html, False, False),
        ("2 · Hard rules first", rules(pre) + (f'<span class="sg-fact">decided: {chip(output["decision"])}</span>'
                                                if pre_fired else ""), bool(pre_fired), False),
        ("3 · Trained model", m_html, bool(model) and not post_fired, not model),
        ("4 · Checks after", rules(post) if post else '<span class="sg-fact">skipped</span>', bool(post_fired),
         not post),
    ]
    cells = "".join(f'<div class="sg-layer {"decided" if d else ""} {"skipped" if sk else ""}"><div class="lt">{t}</div>'
                    f'{body}</div>' for t, body, d, sk in layers)
    note = f'<p style="margin:6px 2px 0;font-size:.85rem;color:var(--sg-ink2)">Why: {md(why)}</p>' if why else ""
    return f'<div class="sg-path">{cells}</div>{note}'


def numbers(items: list[tuple[str, str]]) -> None:
    """A strip of big numbers: [(value, label)]."""
    cells = "".join(f'<div class="sg-num"><b>{esc(v)}</b><span>{esc(lbl)}</span></div>' for v, lbl in items)
    show(f'<div class="sg-numbers">{cells}</div>')


def scoreboard(runs, case) -> None:
    """One line: each gate's verdict on this case."""
    bits = []
    for r in runs:
        if r.trace is None:
            bits.append(f'<span class="sg-score none" title="{esc(r.note)}">{esc(r.gate.code)} –</span>')
            continue
        v = X.verdict(r.trace, case)
        sym = {"success": "✓", "warning": "!", "error": "✕"}[v.tone]
        bits.append(f'<span class="sg-score {v.tone}" title="{esc(r.gate.name)}: {esc(v.label)}">'
                    f'{esc(r.gate.code)} {sym}</span>')
    show(f'<div class="sg-scoreboard"><span class="lbl">Who got it right</span>{"".join(bits)}</div>')


CALLOUT_ICON = {"catch": "warning", "lesson": "lightbulb", "right": "check_circle", "new": "info"}


def callout(kind: str, label: str, text: str) -> None:
    show(f'<div class="sg-callout {kind}">{icon(CALLOUT_ICON.get(kind, "info"), "lead")}<div><b>{esc(label)}</b> '
         f'{md(text)}</div></div>')


def section(label: str) -> None:
    show(f'<div class="sg-section-label">{esc(label)}</div>')


def cards(items: list[dict], two: bool = False, four: bool = False) -> None:
    """items: {kicker?, title, body (html-safe or plain), status?}"""
    out = []
    for it in items:
        kicker = f'<div class="sg-kicker">{it["kicker"]}</div>' if it.get("kicker") else ""
        body = it.get("html") or f'<p>{md(it.get("body", ""))}</p>'
        out.append(f'<div class="sg-card {it.get("status", "")}">{kicker}<h4>{it["title"]}</h4>{body}</div>')
    show(f'<div class="sg-grid {"two" if two else "four" if four else ""}">{"".join(out)}</div>')


def stat_tile(label: str, value: str, sub: str, target: tuple[str, str] | None = None, note: str = "") -> str:
    t = f'<div class="sg-target {target[0]}">{esc(target[1])}</div>' if target else ""
    n = f'<div class="sg-note">{esc(note)}</div>' if note else ""
    return (f'<div class="sg-card"><div class="sg-kicker">{esc(label)}</div>'
            f'<div class="sg-stat">{esc(value)} <small>{esc(sub)}</small></div>{n}{t}</div>')


# ---------------------------------------------------------------- evidence

def evidence_cards(items: list[X.EvidenceItem], compact: bool = False) -> None:
    sym = {"ok": "✓", "warn": "!", "bad": "✕", "info": "i"}
    out = []
    for it in items:
        pts = "".join(f'<li><span class="sg-dot {s}">{sym[s]}</span><span>{md(t)}</span></li>' for s, t in it.points)
        out.append(f'<div class="sg-card {it.status}"><div class="sg-kicker">{icon(it.icon)}{esc(it.kind)}</div>'
                   f'<h4>{md(it.headline)}</h4><ul>{pts}</ul></div>')
    show(f'<div class="sg-grid {"compact" if compact else "two"}">{"".join(out)}</div>')


def user_bubble(text: str) -> None:
    show(f'<div class="sg-bubble user"><span class="who">User</span>{esc(text)}</div>')


def agent_steps(gi) -> None:
    rows = []
    for p in gi.prior_calls:
        rows.append(f'<div class="sg-step"><div class="ico">{icon("visibility")}</div><div class="body"><div class="title">'
                    f'Reads: <code>{esc(p["function"])}</code></div><div class="sub">Read-only, so it passes '
                    f'without a check. What it returned is shown below as untrusted content.</div></div></div>')
    for h in gi.resolution_history:
        who = "The user" if h.get("responder") == "user" else f"The approver ({esc(h.get('responder'))})"
        rows.append(f'<div class="sg-step"><div class="ico">{icon("forum")}</div><div class="body"><div class="title">'
                    f'Earlier round: the gate said {chip(h.get("kind"))}</div><div class="sub">{who} answered: '
                    f'<i>“{esc(h.get("response", ""))}”</i></div></div></div>')
    call = gi.proposed_call
    args = json.dumps(call.get("args") or {}, indent=2, ensure_ascii=False)
    rows.append(f'<div class="sg-step"><div class="ico risky">{icon("bolt")}</div><div class="body"><div class="title">'
                f'Wants to run: <code>{esc(call["function"])}</code></div><div class="sub">This changes something, '
                f'so it is stopped at the gate before it runs.</div><div class="sg-code">{esc(args)}</div></div></div>')
    show("".join(rows))


def untrusted(gi) -> None:
    inj = X.injected_block(gi)
    for t in gi.untrusted_content:
        flag = inj == t["id"]
        label = ("The instruction behind the action came from this text" if flag
                 else "Treated as data, never as instructions")
        show(f'<div class="sg-step"><div class="ico{" risky" if flag else ""}">{icon("warning" if flag else "description")}'
             f'</div><div class="body"><div class="title">'
             f'{esc(t["id"])} · {md(X.source_plain(t.get("source")))}</div><div class="sub">{esc(label)}</div>'
             f'<div class="sg-quote {"" if flag else "plain"}">{esc(t.get("text", ""))}</div></div></div>')


# ---------------------------------------------------------------- decisions

def flow(trace: dict) -> str:
    parts = []
    for r in trace["rounds"]:
        out = r["output"]
        if r["round"] > 0:
            parts.append('<span class="arrow">→</span>')
        parts.append(chip(out["decision"]))
        resp = r.get("response")
        if resp:
            who = "User" if resp.get("responder") == "user" else "Approver"
            txt = resp.get("text") or "—"
            parts.append(f'<span class="arrow">→</span><span class="sg-reply"><b>{who}:</b> {esc(txt)}</span>')
    if trace.get("defaulted"):
        parts.append('<span class="arrow">→</span><span class="sg-reply">still unsure after 2 rounds, '
                     f'so blocked by default</span><span class="arrow">⇒</span>{chip(trace["final_decision"])}')
    return f'<div class="sg-flow">{"".join(parts)}</div>'


def comparison(runs: list[GateRun], case) -> None:
    head = "<tr><th>Gate</th><th>What happened</th><th>Final</th><th>Result</th></tr>"
    body = []
    # highlight the newest gate that has a result here (the final design, or GateExp v2 where it is held back)
    hi = NEWEST if any(r.gate.key == NEWEST and r.trace is not None for r in runs) else PREV_GX
    for r in runs:
        g = r.gate
        new = ' <span class="sg-tag new">final</span>' if g.key == NEWEST else ""
        live = ' <span class="sg-tag">computed live</span>' if r.source == "live" else ""
        name = f'<div class="gname">{esc(g.code)} · {esc(g.name)}{new}{live}<small>{esc(g.blurb)}</small></div>'
        if r.trace is None:
            body.append(f'<tr><td>{name}</td><td colspan="3" class="muted">{esc(r.note)}</td></tr>')
            continue
        v = X.verdict(r.trace, case)
        cls = "ours" if g.key == hi else ""
        body.append(f'<tr class="{cls}"><td>{name}</td><td>{flow(r.trace)}</td>'
                    f'<td>{chip(r.trace["final_decision"])}</td><td class="res">{verdict(v)}</td></tr>')
    show(f'<div class="sg-table-wrap"><table class="sg-table">{head}{"".join(body)}</table></div>')


def prob_bars(probs: dict[str, float]) -> str:
    rows = []
    for d in X.DECISIONS:
        if d not in probs:
            continue
        p = probs[d]
        rows.append(f'<div class="sg-bar"><span>{chip(d)}</span><div class="track"><div class="fill" '
                    f'style="width:{max(p * 100, 0.5):.1f}%"></div></div><span class="v">{p:.0%}</span></div>')
    return f'<div class="sg-bars">{"".join(rows)}</div>'


def note(text: str) -> None:
    """Small grey text that understands **bold**, `code` and [[glossary]] tooltips."""
    show(f'<p class="sg-note-p">{md(text)}</p>')


def lead(text: str) -> None:
    """A paragraph that understands **bold**, `code` and [[glossary]] tooltips."""
    show(f'<p class="sg-lead">{md(text)}</p>')
