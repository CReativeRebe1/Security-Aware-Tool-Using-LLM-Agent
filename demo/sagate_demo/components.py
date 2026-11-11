"""Small HTML components rendered with st.html. Every piece of data text goes through `esc` (or `md`, which
escapes and then turns `code` spans into <code>), so nothing from a case file can inject markup."""

from __future__ import annotations

import html
import json
import re

import streamlit as st

from . import data as D
from . import explain as X
from .gates import OURS, GateRun


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def md(s) -> str:
    """Escape, then render `code`, **bold** and *italic*."""
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s))
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    return re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<i>\1</i>", out)


def show(markup: str) -> None:
    st.html(markup)


def load_css() -> None:
    st.html(f"<style>{D.asset('style.css')}</style>")


# ---------------------------------------------------------------- atoms

def chip(decision: str | None) -> str:
    if not decision:
        return '<span class="sg-chip NONE">—</span>'
    return f'<span class="sg-chip {esc(decision)}">{X.DECISION_ICON.get(decision, "")} {esc(decision)}</span>'


def tag(text: str, cls: str = "") -> str:
    return f'<span class="sg-tag {cls}">{esc(text)}</span>'


def verdict(v: X.Verdict | None) -> str:
    if v is None:
        return '<span class="sg-verdict none">not scored</span>'
    icon = {"success": "✓", "warning": "!", "error": "✕"}[v.tone]
    return f'<span class="sg-verdict {v.tone}">{icon} {esc(v.short)}</span>'


def hero(eyebrow: str, title: str, text: str) -> None:
    show(f'<div class="sg-hero"><div class="sg-eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1>'
         f'<p>{esc(text)}</p></div>')


def callout(kind: str, label: str, text: str) -> None:
    show(f'<div class="sg-callout {kind}"><b>{esc(label)}</b> {md(text)}</div>')


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

def evidence_cards(items: list[X.EvidenceItem]) -> None:
    sym = {"ok": "✓", "warn": "!", "bad": "✕", "info": "i"}
    out = []
    for it in items:
        pts = "".join(f'<li><span class="sg-dot {s}">{sym[s]}</span><span>{md(t)}</span></li>' for s, t in it.points)
        out.append(f'<div class="sg-card {it.status}"><div class="sg-kicker">{it.icon} {esc(it.kind)}</div>'
                   f'<h4>{md(it.headline)}</h4><ul>{pts}</ul></div>')
    show(f'<div class="sg-grid two">{"".join(out)}</div>')


def user_bubble(text: str) -> None:
    show(f'<div class="sg-bubble user"><span class="who">User</span>{esc(text)}</div>')


def agent_steps(gi) -> None:
    rows = []
    for p in gi.prior_calls:
        rows.append(f'<div class="sg-step"><div class="ico">👁️</div><div class="body"><div class="title">'
                    f'Reads: <code>{esc(p["function"])}</code></div><div class="sub">Read-only, so it passes '
                    f'without a check. What it returned is shown below as untrusted content.</div></div></div>')
    for h in gi.resolution_history:
        who = "The user" if h.get("responder") == "user" else f"The approver ({esc(h.get('responder'))})"
        rows.append(f'<div class="sg-step"><div class="ico">💬</div><div class="body"><div class="title">'
                    f'Earlier round: the gate said {chip(h.get("kind"))}</div><div class="sub">{who} answered: '
                    f'<i>“{esc(h.get("response", ""))}”</i></div></div></div>')
    call = gi.proposed_call
    args = json.dumps(call.get("args") or {}, indent=2, ensure_ascii=False)
    rows.append(f'<div class="sg-step"><div class="ico risky">⚡</div><div class="body"><div class="title">'
                f'Wants to run: <code>{esc(call["function"])}</code></div><div class="sub">This changes something, '
                f'so it is stopped at the gate before it runs.</div><div class="sg-code">{esc(args)}</div></div></div>')
    show("".join(rows))


def untrusted(gi) -> None:
    inj = X.injected_block(gi)
    for t in gi.untrusted_content:
        flag = inj == t["id"]
        label = ("⚠️ The instruction behind the action came from this text" if flag
                 else "Treated as data, never as instructions")
        show(f'<div class="sg-step"><div class="ico">📄</div><div class="body"><div class="title">'
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
    for r in runs:
        g = r.gate
        name = f'<div class="gname">{esc(g.code)} · {esc(g.name)}<small>{esc(g.blurb)}</small></div>'
        if r.trace is None:
            body.append(f'<tr><td>{name}</td><td colspan="3" class="muted">{esc(r.note)}</td></tr>')
            continue
        v = X.verdict(r.trace, case)
        cls = "ours" if g.key == OURS else ""
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
