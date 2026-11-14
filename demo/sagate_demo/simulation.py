"""The race: several gates decide the same cases, in the same order, animated in the browser.

Every tile is one real case and one real recorded decision (or, for B1 on the red-team set, one computed here).
The animation is plain HTML + JavaScript in an iframe, so it plays smoothly without server round-trips.
"""

from __future__ import annotations

import json
import random

from . import data as D
from . import explain as X
from .gates import GATES, recorded

# tone -> (colour, symbol, label). Checked for colour-blind safety; symbols carry the meaning too.
TONES = {
    "ok": ("#3987e5", "", "Correct"),                                 # dark-mode steps, checked on the dark
    "extra": ("#c98500", "?", "Right outcome, but asked a question nobody needed"),   # surface
    "skip": ("#c98500", "!", "Ran it without the user's confirmation"),
    "unsafe": ("#e34948", "✕", "Unsafe: an action ran that should not have"),
    "over": ("#64748b", "–", "Over-blocked: a good action was refused"),
    "wrong": ("#e34948", "✕", "Wrong outcome"),
    "none": ("var(--none)", "", "Not scored for this gate"),       # follows the dark / light theme
}


def _tone(v: X.Verdict) -> str:
    if v.tone == "success":
        return "ok"
    if v.tone == "warning":
        return "extra" if v.ok else "skip"
    if v.short == "Unsafe":
        return "unsafe"
    if v.short == "Over-blocked":
        return "over"
    return "wrong"


def payload(split: str, keys: list[str], seed: int = 7, order: str = "shuffled") -> dict:
    cases = D.cases(split)
    ids = list(cases)
    if order == "shuffled":
        random.Random(seed).shuffle(ids)
    else:
        ids.sort(key=lambda c: (X.CATEGORY_PLAIN.get(cases[c].category, cases[c].category or ""), c))
    lanes = []
    for k in keys:
        preds = recorded.preds(split, k) or {}
        tiles = []
        for cid in ids:
            p = preds.get(cid)
            if p is None:
                tiles.append(["none", "", ""])
                continue
            v = X.verdict(p, cases[cid])
            tiles.append([_tone(v), p["first_decision"], p["final_decision"]])
        g = GATES[k]
        lanes.append({"code": g.code, "name": g.name, "tiles": tiles})
    meta = [{"req": (cases[c].input.user.get("prompt") or "")[:140],
             "kind": X.CATEGORY_PLAIN.get(cases[c].category, cases[c].category or ""),
             "gold": f"{cases[c].gold_decision} → {cases[c].gold_final_action}"} for c in ids]
    return {"lanes": lanes, "cases": meta, "tones": {k: list(v) for k, v in TONES.items()}}


def html_page(data: dict, seconds: float = 14.0) -> str:
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")      # safe inside <script>
    return TEMPLATE.replace("__DATA__", blob).replace("__SECONDS__", str(seconds))


TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
<style>
:root { --ink:#e2e8f0; --ink2:#94a3b8; --ink3:#64748b; --line:rgba(148,163,184,.16); --soft:#1e293b; --none:#1e293b; --blue:#818cf8; }
html.light { --ink:#0f172a; --ink2:#475569; --ink3:#64748b; --line:rgba(30,41,90,.12); --soft:#e2e8f0; --none:#e2e8f0; }
html.light .lane { background: rgba(255,255,255,.62); border-color: rgba(255,255,255,.9); box-shadow: 0 14px 34px -22px rgba(30,41,90,.35); }
html.light .lane-name { color: #0b1020; }
html.light button { background: rgba(255,255,255,.75); border-color: rgba(255,255,255,.95); color: #1e293b;
  box-shadow: 0 6px 16px -10px rgba(30,41,90,.4); }
html.light button:hover:not(:disabled) { color: #3730a3; border-color: #818cf8; background: #fff; }
html.light button.primary { color: #fff; border-color: #6366f1; background: linear-gradient(180deg, #6d68f2, #4f46e5); }
html.light .progress { background: rgba(30,41,90,.08); }
html.light .t:hover { outline-color: #0f172a; }
html.light .done { color: #047857; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, sans-serif; color: var(--ink); background: transparent; }
.bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
button { font: 600 14px Inter, sans-serif; border-radius: 10px; border: 1px solid rgba(148,163,184,.28);
  background: rgba(255,255,255,.04); padding: 8px 16px; cursor: pointer; color: var(--ink);
  transition: border-color .15s ease, color .15s ease; }
button:hover:not(:disabled) { border-color: #818cf8; color: #fff; background: rgba(99,102,241,.14); }
button.primary { background: linear-gradient(180deg, #6d68f2, #4f46e5); color: #fff; border-color: #6366f1;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.2), 0 10px 24px -10px rgba(99,102,241,.9); }
button.primary:hover:not(:disabled) { color: #fff; border-color: #818cf8; background: linear-gradient(180deg, #6d68f2, #4f46e5); }
button:disabled { opacity: .5; cursor: default; }
.speed { font-size: 13px; color: var(--ink2); display: flex; align-items: center; gap: 6px; }
.progress { flex: 1; min-width: 160px; height: 8px; background: rgba(255,255,255,.08); border-radius: 999px; overflow: hidden; }
.progress > div { height: 100%; width: 0; background: linear-gradient(90deg, #6366f1, #7dd3fc); transition: width .1s linear;
  border-radius: 999px; }
.count { font: 700 13px Inter; color: var(--ink2); min-width: 86px; text-align: right; }
.lane { background: rgba(255,255,255,.035); border: 1px solid var(--line); border-radius: 14px; padding: 13px 16px;
  margin-bottom: 10px; }
.lane-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.lane-name { font: 800 15px Inter; color: #f8fafc; }
.lane-name small { font: 500 12px Inter; color: var(--ink3); margin-left: 6px; }
.stats { display: flex; gap: 12px; font-size: 12.5px; color: var(--ink2); flex-wrap: wrap; }
.stats b { font: 800 14px Inter; color: var(--ink); font-variant-numeric: tabular-nums; }
.grid { display: flex; flex-wrap: wrap; gap: 3px; }
.t { width: 15px; height: 15px; border-radius: 3px; background: var(--soft); font: 700 10px/15px Inter; color: #fff;
  text-align: center; transition: transform .15s ease; }
.t.on { animation: pop .25s ease; }
@keyframes pop { 0% { transform: scale(.3); } 70% { transform: scale(1.25); } 100% { transform: scale(1); } }
.t:hover { outline: 2px solid #fff; outline-offset: 1px; }
.now { background: radial-gradient(420px 160px at 100% 0%, rgba(99,102,241,.45), transparent 65%),
  linear-gradient(160deg, #0b1220, #111a2e 60%, #1e1b4b); color: #e2e8f0; border-radius: 14px; padding: 13px 18px;
  margin: 6px 0 12px; font-size: 14px; min-height: 74px; border: 1px solid rgba(255,255,255,.14);
  box-shadow: 0 18px 36px -22px rgba(19,54,107,.7), inset 0 1px 0 rgba(255,255,255,.14); }
.now .k { font: 700 11px Inter; text-transform: uppercase; letter-spacing: .1em; color: #a5b4fc; }
.now .req { font-size: 15px; margin: 4px 0 8px; color: #fff; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { font: 700 11.5px Inter; padding: 2px 9px; border-radius: 999px; background: rgba(255,255,255,.12);
  border: 1px solid rgba(255,255,255,.14); color: #dbe8fb; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--ink2); margin: 4px 0 10px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 14px; height: 14px; border-radius: 3px; display: inline-block; font: 700 10px/14px Inter;
  color: #fff; text-align: center; font-style: normal; }
.tip { position: fixed; pointer-events: none; background: rgba(13,26,52,.94); color: #e7eefb; font-size: 12.5px;
  padding: 8px 11px; border-radius: 10px; border: 1px solid rgba(255,255,255,.12); max-width: 320px; display: none; z-index: 9; line-height: 1.4; }
.done { font: 600 13px Inter; color: #34d399; display: none; }
</style></head><body>
<div class="bar">
  <button class="primary" id="play">▶ Play</button>
  <button id="pause" disabled>Pause</button>
  <button id="reset">↺ Restart</button>
  <label class="speed">Speed <input type="range" id="speed" min="1" max="5" value="2"></label>
  <div class="progress"><div id="prog"></div></div>
  <div class="count" id="cnt">0 / 0</div>
</div>
<div class="legend" id="legend"></div>
<div class="now" id="now"><div class="k">Press ▶ Play</div><div class="req">Every gate will decide the same cases, in the
  same order. Each square is one real case.</div></div>
<div id="lanes"></div>
<div class="done" id="done">✓ Done. Hover any square to see the case.</div>
<div class="tip" id="tip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const D = JSON.parse(document.getElementById('data').textContent);
// follow the app's theme (the app sets <html data-sg-theme> on its page)
(function themeSync() { try { const t = window.parent.document.documentElement.getAttribute('data-sg-theme');
  document.documentElement.classList.toggle('light', t === 'light'); } catch (e) {} setTimeout(themeSync, 400); })();
const N = D.cases.length, T = D.tones, BASE = __SECONDS__ * 1000;
const lanesEl = document.getElementById('lanes');
const order = ["ok","extra","skip","unsafe","over","none"];
document.getElementById('legend').innerHTML = order.map(k =>
  `<span><i style="background:${T[k][0]}">${T[k][1]}</i>${T[k][2]}</span>`).join('');
const lanes = D.lanes.map((ln, li) => {
  const el = document.createElement('div'); el.className = 'lane';
  el.innerHTML = `<div class="lane-head"><div class="lane-name">${esc(ln.code)}<small>${esc(ln.name)}</small></div>
    <div class="stats"><span>✓ right outcome <b id="c${li}">0</b></span><span>? needless question <b id="w${li}">0</b></span>
    <span>! skipped confirmation <b id="s${li}">0</b></span><span>✕ unsafe <b id="u${li}">0</b></span>
    <span>– over-blocked <b id="o${li}">0</b></span></div></div>
    <div class="grid" id="g${li}"></div>`;
  lanesEl.appendChild(el);
  const g = el.querySelector('.grid');
  const tiles = ln.tiles.map((t, i) => { const d = document.createElement('div'); d.className = 't';
    d.dataset.lane = li; d.dataset.i = i; g.appendChild(d); return d; });
  return {ln, tiles, n: {ok:0, extra:0, skip:0, unsafe:0, over:0, wrong:0}};
});
let i = 0, timer = null;
const tip = document.getElementById('tip');
function step() {
  if (i >= N) { stop(); document.getElementById('done').style.display = 'block'; return; }
  const c = D.cases[i];
  let chips = '';
  lanes.forEach((L, li) => {
    const [tone, first, fin] = L.ln.tiles[i]; const el = L.tiles[i];
    el.style.background = T[tone][0]; el.textContent = T[tone][1]; el.classList.add('on');
    if (tone in L.n) L.n[tone]++;
    document.getElementById('c'+li).textContent = L.n.ok + L.n.extra;
    document.getElementById('w'+li).textContent = L.n.extra;
    document.getElementById('s'+li).textContent = L.n.skip;
    document.getElementById('u'+li).textContent = L.n.unsafe + L.n.wrong;
    document.getElementById('o'+li).textContent = L.n.over;
    chips += `<span class="chip">${esc(L.ln.code)}: ${first ? first + (fin && fin !== first ? ' → ' + fin : '') : '—'} ${T[tone][1] || (tone==='ok' ? '✓' : '')}</span>`;
  });
  document.getElementById('now').innerHTML = `<div class="k">Case ${i+1} of ${N} · ${esc(c.kind)} · right answer ${esc(c.gold)}</div>
    <div class="req">“${esc(c.req)}”</div><div class="chips">${chips}</div>`;
  i++;
  document.getElementById('prog').style.width = (100*i/N) + '%';
  document.getElementById('cnt').textContent = i + ' / ' + N;
}
function speed() { return BASE / N / [0, .5, 1, 2, 4, 10][+document.getElementById('speed').value]; }
function play() { if (i >= N) reset(); stop(); timer = setInterval(step, speed());
  document.getElementById('play').disabled = true; document.getElementById('pause').disabled = false; }
function stop() { clearInterval(timer); timer = null; document.getElementById('play').disabled = false;
  document.getElementById('pause').disabled = true; }
function reset() { stop(); i = 0; document.getElementById('done').style.display = 'none';
  lanes.forEach((L, li) => { L.tiles.forEach(t => { t.style.background = ''; t.textContent = ''; t.classList.remove('on'); });
    for (const k in L.n) L.n[k] = 0; ['c','w','s','u','o'].forEach(p => document.getElementById(p+li).textContent = 0); });
  document.getElementById('prog').style.width = '0'; document.getElementById('cnt').textContent = '0 / ' + N; }
document.getElementById('play').onclick = play;
document.getElementById('pause').onclick = stop;
document.getElementById('reset').onclick = reset;
document.getElementById('speed').oninput = () => { if (timer) { stop(); play(); } };
document.getElementById('cnt').textContent = '0 / ' + N;
lanesEl.addEventListener('mousemove', e => {
  const t = e.target.closest('.t'); if (!t || +t.dataset.i >= i) { tip.style.display = 'none'; return; }
  const L = lanes[+t.dataset.lane], k = +t.dataset.i, [tone, first, fin] = L.ln.tiles[k], c = D.cases[k];
  tip.innerHTML = `<b>${esc(L.ln.code)}</b> · ${esc(T[tone][2])}<br>“${esc(c.req)}”<br>Gate: ${esc(first || '—')}${fin && fin !== first ? ' → ' + esc(fin) : ''} · right: ${esc(c.gold)}`;
  tip.style.display = 'block'; tip.style.left = Math.min(e.clientX + 12, window.innerWidth - 330) + 'px'; tip.style.top = (e.clientY + 12) + 'px';
});
lanesEl.addEventListener('mouseleave', () => tip.style.display = 'none');
</script>
</body></html>"""
