"""The animated "gate in front of every risky action" diagram (home page and How it works).

A self-contained HTML page shown with st.iframe: SVG connectors and moving packets, HTML nodes on top. It loops
through one example per decision (the same examples as explain.DECISION_EXAMPLE): the request reaches the agent,
the four kinds of evidence light up, the gate decides, the chosen branch lights up, and for ASK_USER / ESCALATE the
answer flows back to the gate. It is an illustration of the design, not a recorded case; the page says so.
"""

from __future__ import annotations

import json

from . import explain as X

# Per decision: evidence status (where it came from, who may approve, how secret, which rules apply), what the
# gate says, and the answer that comes back for the question decisions.
SCENES = {
    "ALLOW": {"ev": ["ok", "ok", "ok", "ok"], "why": "Known payee, within the user's limit.", "answer": None,
              "final": "The payment runs."},
    "BLOCK": {"ev": ["bad", "ok", "warn", "ok"], "why": "The instruction came from an email, not the user.",
              "answer": None, "final": "Nothing is sent."},
    "ASK_USER": {"ev": ["ok", "ok", "ok", "warn"], "why": "Two meetings match: which one?",
                 "answer": "User: “The one on Monday.”", "final": "Then ALLOW: only that meeting is deleted."},
    "ESCALATE": {"ev": ["ok", "bad", "ok", "ok"], "why": "3,000 is above the user's 1,500 limit.",
                 "answer": "Manager: “Approved.”", "final": "Then ALLOW: the payment runs after approval."},
}


def html_page() -> str:
    data = [{"d": d, "example": X.DECISION_EXAMPLE[d], **SCENES[d]} for d in X.DECISIONS]
    return TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root { --brand:#6366f1; --brand2:#a5b4fc; --ok:#10b981; --bad:#ef4444; --ask:#0ea5e9; --warn:#f59e0b;
  --ink:#e2e8f0; --ink2:#94a3b8; --line:rgba(148,163,184,.28); }
* { box-sizing: border-box; }
html, body { margin: 0; background: transparent; font-family: Inter, system-ui, sans-serif; color: var(--ink); }
.panel { position: relative; border-radius: 20px; overflow: hidden; padding: 18px 18px 14px;
  background: radial-gradient(560px 280px at 62% 40%, rgba(99,102,241,.28), transparent 70%),
              radial-gradient(420px 240px at 0% 100%, rgba(56,189,248,.12), transparent 70%),
              linear-gradient(160deg, #0b1220, #111a2e 60%, #161b3d); border: 1px solid rgba(255,255,255,.08); }
.panel::before { content:""; position:absolute; inset:0; pointer-events:none; opacity:.45;
  background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px);
  background-size: 32px 32px; -webkit-mask-image: radial-gradient(ellipse 75% 80% at 55% 45%, #000 35%, transparent 80%);
  mask-image: radial-gradient(ellipse 75% 80% at 55% 45%, #000 35%, transparent 80%); }
.scroll { overflow-x: auto; }
.stage { position: relative; min-width: 760px; aspect-ratio: 1120 / 470; container-type: inline-size; }
svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.wire { fill: none; stroke: var(--line); stroke-width: 2; transition: stroke .35s ease, opacity .35s ease; }
.wire.ans { stroke-dasharray: 6 6; }
.wire.on { stroke: var(--brand2); filter: drop-shadow(0 0 6px rgba(165,180,252,.8)); }
.wire.dim { opacity: .35; }
.pkt { filter: drop-shadow(0 0 8px currentColor); }
.node { position: absolute; border-radius: 14px; background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12);
  display: flex; align-items: center; gap: .6em; padding: 0 1em; font-size: clamp(10px, 1.32cqw, 15px); font-weight: 600;
  transition: border-color .35s ease, box-shadow .35s ease, background .35s ease, opacity .35s ease;
  -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); }
.node svg.i { position: static; width: 1.5em; height: 1.5em; flex: none; stroke: currentColor; fill: none; stroke-width: 1.8;
  stroke-linecap: round; stroke-linejoin: round; }
.node.on { border-color: rgba(165,180,252,.7); box-shadow: 0 0 0 4px rgba(99,102,241,.18), 0 10px 30px -10px rgba(99,102,241,.8);
  background: rgba(99,102,241,.14); }
.node small { display: block; font-size: .78em; font-weight: 500; color: var(--ink2); margin-top: .1em; }
.ev { flex-direction: column; align-items: stretch; justify-content: center; padding: .7em .9em; gap: .45em; }
.ev .t { font-size: .8em; text-transform: uppercase; letter-spacing: .12em; color: var(--ink2); }
.chips { display: grid; grid-template-columns: 1fr 1fr; gap: .4em; }
.chip { display: flex; align-items: center; gap: .45em; font-size: .82em; font-weight: 500; padding: .35em .55em; border-radius: 9px;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); color: #cbd5e1; transition: all .3s ease; }
.chip i { width: .55em; height: .55em; border-radius: 50%; background: #475569; flex: none; transition: all .3s ease; }
.chip.ok i { background: var(--ok); box-shadow: 0 0 8px var(--ok); } .chip.bad i { background: var(--bad); box-shadow: 0 0 8px var(--bad); }
.chip.warn i { background: var(--warn); box-shadow: 0 0 8px var(--warn); }
.chip.bad { border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.1); }
.chip.warn { border-color: rgba(245,158,11,.4); background: rgba(245,158,11,.08); }
.gate { justify-content: center; flex-direction: column; gap: .2em; font-size: clamp(11px, 1.55cqw, 17px); font-weight: 800;
  background: linear-gradient(160deg, #6366f1, #4338ca); border-color: rgba(165,180,252,.6); color: #fff; }
.gate .shield { width: 1.9em; height: 1.9em; stroke: #fff; fill: rgba(255,255,255,.15); stroke-width: 1.8; }
.gate.think { animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(99,102,241,.55), 0 10px 40px -10px rgba(99,102,241,.9); }
  50% { box-shadow: 0 0 0 14px rgba(99,102,241,0), 0 10px 40px -10px rgba(99,102,241,.9); } }
.verdict { position: absolute; transform: translate(-50%, 0); font-size: clamp(9px, 1.15cqw, 13px); font-weight: 800; letter-spacing: .05em;
  padding: .3em .8em; border-radius: 999px; opacity: 0; transition: opacity .3s ease, transform .3s ease; white-space: nowrap; }
.verdict.show { opacity: 1; transform: translate(-50%, -4px); }
.out { font-size: clamp(10px, 1.3cqw, 15px); }
.out .dot { width: .7em; height: .7em; border-radius: 50%; flex: none; }
.out.ALLOW .dot { background: var(--ok); } .out.BLOCK .dot { background: var(--bad); }
.out.ASK_USER .dot { background: var(--ask); } .out.ESCALATE .dot { background: var(--warn); }
.out.on.ALLOW { border-color: var(--ok); box-shadow: 0 0 0 4px rgba(16,185,129,.18), 0 10px 30px -10px rgba(16,185,129,.8); background: rgba(16,185,129,.12); }
.out.on.BLOCK { border-color: var(--bad); box-shadow: 0 0 0 4px rgba(239,68,68,.18), 0 10px 30px -10px rgba(239,68,68,.8); background: rgba(239,68,68,.12); }
.out.on.ASK_USER { border-color: var(--ask); box-shadow: 0 0 0 4px rgba(14,165,233,.18), 0 10px 30px -10px rgba(14,165,233,.8); background: rgba(14,165,233,.12); }
.out.on.ESCALATE { border-color: var(--warn); box-shadow: 0 0 0 4px rgba(245,158,11,.18), 0 10px 30px -10px rgba(245,158,11,.8); background: rgba(245,158,11,.12); }
.out.dim, .node.dim { opacity: .45; }
.lbl { position: absolute; transform: translate(-50%, -50%); font-size: clamp(8px, 1.02cqw, 12px); font-weight: 700; letter-spacing: .04em;
  color: var(--ink2); background: #0f172a; padding: .15em .5em; border-radius: 6px; border: 1px solid rgba(255,255,255,.08);
  transition: color .3s ease, border-color .3s ease; white-space: nowrap; }
.lbl.on { color: #fff; border-color: rgba(165,180,252,.6); }
.bubble { position: absolute; left: 1.8%; top: 3%; width: 41%; font-size: clamp(10px, 1.3cqw, 15px); line-height: 1.45;
  background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12); border-radius: 14px 14px 14px 4px; padding: .7em .95em;
  transition: opacity .35s ease; }
.bubble .k { font-size: .72em; text-transform: uppercase; letter-spacing: .12em; color: var(--brand2); font-weight: 700; }
.bubble .q { color: #fff; font-weight: 600; margin-top: .15em; }
.bubble .w { color: var(--ink2); margin-top: .35em; font-size: .9em; min-height: 1.3em; }
.bubble .w b { color: #fff; }
.foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; flex-wrap: wrap; position: relative; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tab { font: 700 12px Inter, sans-serif; letter-spacing: .04em; color: var(--ink2); background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.1); border-radius: 999px; padding: 5px 12px; cursor: pointer; transition: all .2s ease; }
.tab:hover { color: #fff; border-color: rgba(165,180,252,.5); }
.tab.on { color: #fff; background: rgba(99,102,241,.25); border-color: rgba(165,180,252,.6); }
.tab .bar { display: block; height: 2px; margin-top: 4px; border-radius: 2px; background: rgba(255,255,255,.12); overflow: hidden; }
.tab .bar i { display: block; height: 100%; width: 0; background: var(--brand2); }
.note { font-size: 12px; color: var(--ink2); }
</style></head><body>
<div class="panel"><div class="scroll"><div class="stage" id="stage">
<svg viewBox="0 0 1120 470" preserveAspectRatio="none" id="svg">
  <path id="p_ua" class="wire" d="M200,262 L262,262"/>
  <path id="p_ag" class="wire" d="M432,262 L538,240"/>
  <path id="p_eg" class="wire" d="M486,400 C 560,400 590,350 600,300"/>
  <path id="b_ALLOW" class="wire br" d="M702,226 C 790,226 800,56 878,56"/>
  <path id="b_BLOCK" class="wire br" d="M702,244 C 790,244 810,170 878,170"/>
  <path id="b_ASK_USER" class="wire br" d="M702,262 C 790,262 810,284 878,284"/>
  <path id="b_ESCALATE" class="wire br" d="M702,280 C 780,280 800,398 878,398"/>
  <path id="a_ASK_USER" class="wire ans" d="M878,306 C 800,326 740,330 690,300"/>
  <path id="a_ESCALATE" class="wire ans" d="M878,420 C 760,452 670,400 650,300"/>
  <g id="pk"></g>
</svg>
<div class="node" id="n_user" style="left:1.8%;top:47%;width:16%;height:17%"><svg class="i" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg><span>User request</span></div>
<div class="node" id="n_agent" style="left:23.4%;top:47%;width:15.2%;height:17%"><svg class="i" viewBox="0 0 24 24"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M9 17h6"/></svg><span>AI agent</span></div>
<div class="node ev" id="n_ev" style="left:18%;top:70%;width:25.4%;height:27%"><div class="t">Evidence</div><div class="chips">
  <div class="chip" id="c0"><i></i>where it came from</div><div class="chip" id="c1"><i></i>who may approve</div>
  <div class="chip" id="c2"><i></i>how secret</div><div class="chip" id="c3"><i></i>which rules apply</div></div></div>
<div class="node gate" id="n_gate" style="left:48.1%;top:41%;width:14.6%;height:23%"><svg class="i shield" viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 5-3 8.5-7 10-4-1.5-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg><span>SA-Gate</span></div>
<div class="verdict" id="verdict" style="left:55.4%;top:33%"></div>
<div class="node out ALLOW" id="o_ALLOW" style="left:78.4%;top:5.5%;width:19.6%;height:13%"><span class="dot"></span>Action runs</div>
<div class="node out BLOCK" id="o_BLOCK" style="left:78.4%;top:29.8%;width:19.6%;height:13%"><span class="dot"></span>Refused</div>
<div class="node out ASK_USER" id="o_ASK_USER" style="left:78.4%;top:53.9%;width:19.6%;height:13%"><span class="dot"></span>Ask the user</div>
<div class="node out ESCALATE" id="o_ESCALATE" style="left:78.4%;top:78.2%;width:19.6%;height:13%"><span class="dot"></span>Ask the manager</div>
<div class="bubble" id="bubble"><div class="k">Example</div><div class="q" id="q"></div><div class="w" id="w"></div></div>
<div id="labels"></div>
</div></div>
<div class="foot"><div class="tabs" id="tabs"></div><div class="note">An illustration of the design · every risky action stops at the gate</div></div>
</div>
<script id="flowdata" type="application/json">__DATA__</script>
<script>
const S = JSON.parse(document.getElementById('flowdata').textContent);
const COL = {ALLOW:'#10b981', BLOCK:'#ef4444', ASK_USER:'#0ea5e9', ESCALATE:'#f59e0b'};
const VB = {w:1120, h:470};
const $ = id => document.getElementById(id);
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// edge labels at the middle of each path
const LBL = [['p_ag','wants to act',-14], ['b_ALLOW','ALLOW',0], ['b_BLOCK','BLOCK',0], ['b_ASK_USER','ASK_USER',0],
             ['b_ESCALATE','ESCALATE',0], ['a_ASK_USER','answer',0], ['a_ESCALATE','answer',0]];
LBL.forEach(([id, text, dy]) => { const p = $(id), L = p.getTotalLength(), pt = p.getPointAtLength(L * (id[0] === 'a' ? .5 : .55));
  const d = document.createElement('div'); d.className = 'lbl'; d.id = 'l_' + id; d.textContent = text;
  d.style.left = (pt.x / VB.w * 100) + '%'; d.style.top = ((pt.y + dy) / VB.h * 100) + '%'; $('labels').appendChild(d); });
// scene tabs
let cur = 0, timer = null, gen = 0;
S.forEach((s, i) => { const b = document.createElement('button'); b.className = 'tab'; b.innerHTML = s.d + '<span class="bar"><i></i></span>';
  b.onclick = () => { cur = i; run(); }; $('tabs').appendChild(b); });
const sleep = ms => new Promise(r => setTimeout(r, reduce ? 0 : ms));
// narrow screens: the stage is wider than the panel, so pan along with the request
const sc = document.querySelector('.scroll');
function pan(frac) { if (sc.scrollWidth > sc.clientWidth + 4)
  sc.scrollTo({left: Math.max(0, frac * sc.scrollWidth - sc.clientWidth / 2), behavior: reduce ? 'auto' : 'smooth'}); }
function packet(pathId, color, ms, my) {
  return new Promise(res => {
    const p = $(pathId), L = p.getTotalLength(), ns = 'http://www.w3.org/2000/svg';
    const c = document.createElementNS(ns, 'circle'); c.setAttribute('r', 7); c.setAttribute('fill', color); c.setAttribute('class', 'pkt');
    c.style.color = color; $('pk').appendChild(c);
    if (reduce) { c.remove(); return res(); }
    const t0 = performance.now();
    function step(t) { if (my !== gen) { c.remove(); return res(); }
      const k = Math.min(1, (t - t0) / ms), e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2, pt = p.getPointAtLength(e * L);
      c.setAttribute('cx', pt.x); c.setAttribute('cy', pt.y);
      if (k < 1) requestAnimationFrame(step); else { c.remove(); res(); } }
    requestAnimationFrame(step); });
}
function reset() {
  document.querySelectorAll('.wire').forEach(w => { w.classList.remove('on', 'dim'); w.style.stroke = ''; w.style.filter = ''; });
  document.querySelectorAll('.node').forEach(n => n.classList.remove('on', 'dim'));
  document.querySelectorAll('.chip').forEach(c => c.className = 'chip');
  document.querySelectorAll('.lbl').forEach(l => { l.classList.remove('on'); l.style.color = ''; l.style.borderColor = ''; });
  $('n_gate').classList.remove('think'); $('verdict').className = 'verdict'; $('w').innerHTML = '';
}
function light(id, color) { const w = $(id); w.classList.add('on'); if (color) { w.style.stroke = color; w.style.filter = `drop-shadow(0 0 6px ${color})`; }
  const l = $('l_' + id); if (l) { l.classList.add('on'); if (color) { l.style.color = color; l.style.borderColor = color; } } }
async function run() {
  const my = ++gen; clearTimeout(timer); reset();
  const s = S[cur], col = COL[s.d];
  document.querySelectorAll('.tab').forEach((t, i) => { t.classList.toggle('on', i === cur); const bar = t.querySelector('.bar i');
    bar.style.transition = 'none'; bar.style.width = '0'; });
  $('q').textContent = s.example; $('n_user').classList.add('on'); pan(0);
  await sleep(500); if (my !== gen) return;
  light('p_ua'); await packet('p_ua', '#a5b4fc', 450, my); if (my !== gen) return;
  $('n_agent').classList.add('on');
  light('p_ag'); light('p_eg'); $('n_ev').classList.add('on');
  const evs = s.ev.map((st, i) => sleep(120 * i).then(() => { if (my === gen) $('c' + i).classList.add(st); }));
  await Promise.all([packet('p_ag', '#a5b4fc', 700, my), packet('p_eg', '#a5b4fc', 700, my), ...evs]); if (my !== gen) return;
  $('n_gate').classList.add('on', 'think'); $('w').textContent = 'Checking the evidence…'; pan(0.55);
  await sleep(900); if (my !== gen) return;
  $('n_gate').classList.remove('think');
  const v = $('verdict'); v.textContent = s.d; v.style.background = col; v.style.color = s.d === 'ESCALATE' ? '#1f1300' : '#fff';
  v.classList.add('show'); $('w').innerHTML = '<b>' + s.d + '</b> · ' + s.why;
  document.querySelectorAll('.br').forEach(b => { if (b.id !== 'b_' + s.d) b.classList.add('dim'); });
  document.querySelectorAll('.out').forEach(o => { if (o.id !== 'o_' + s.d) o.classList.add('dim'); });
  light('b_' + s.d, col); pan(0.85); await packet('b_' + s.d, col, 650, my); if (my !== gen) return;
  $('o_' + s.d).classList.add('on');
  if (s.answer) {
    await sleep(500); if (my !== gen) return;
    light('a_' + s.d, col); $('w').innerHTML = '<b>' + s.d + '</b> · ' + s.why + '<br>' + s.answer;
    await packet('a_' + s.d, col, 800, my); if (my !== gen) return;
    $('n_gate').classList.add('think'); await sleep(450); $('n_gate').classList.remove('think');
  }
  $('w').innerHTML = '<b>' + s.d + '</b> · ' + s.why + (s.answer ? '<br>' + s.answer : '') + '<br><b>' + s.final + '</b>';
  const bar = document.querySelectorAll('.tab')[cur].querySelector('.bar i');
  requestAnimationFrame(() => { bar.style.transition = reduce ? 'none' : 'width 2.6s linear'; bar.style.width = '100%'; });
  if (!reduce) timer = setTimeout(() => { if (my === gen) { cur = (cur + 1) % S.length; run(); } }, 2800);
}
run();
</script></body></html>"""
