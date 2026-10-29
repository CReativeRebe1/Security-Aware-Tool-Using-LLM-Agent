/* Labelling tool. Every change is saved at once: first to this browser (localStorage queue), then to the local
   server, which writes your own vote file. Unsent changes are re-sent on the next load. */

const $ = (id) => document.getElementById(id);
const S = {
  who: null, config: null, batches: [], batchId: null, role: null,
  cases: [], votes: {}, others: {}, idx: 0, policies: [], raw: false, sending: false,
};
const LS = {
  who: 'labeler.who', theme: 'labeler.theme',
  pos: (w) => `labeler.pos.${w}`, queue: (w) => `labeler.queue.${w}`,
};
const DEFAULTS = {
  ALLOW: ['none', 'current_user'], BLOCK: ['none', 'none'],
  ASK_USER: ['user_intent', 'current_user'], ESCALATE: ['approval', 'manager'],
};
const DECISION_COLOR = { ALLOW: 'var(--allow)', BLOCK: 'var(--block)', ASK_USER: 'var(--ask)', ESCALATE: 'var(--esc)' };
const PERSON_COLORS = ['#6366f1', '#ec4899', '#10b981', '#f59e0b', '#06b6d4', '#8b5cf6'];

/* ---------- icons (inline SVG, stroke style) ---------- */
const ICONS = {
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  left: '<path d="m15 18-6-6 6-6"/>', right: '<path d="m9 18 6-6-6-6"/>',
  skip: '<path d="m5 4 10 8-10 8V4z"/><path d="M19 5v14"/>',
  code: '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  help: '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  terminal: '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7l10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  compass: '<circle cx="12" cy="12" r="10"/><path d="m16.2 7.8-2.1 6.3-6.3 2.1 2.1-6.3 6.3-2.1z"/>',
  alert: '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3z"/><path d="M12 9v4M12 17h.01"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  check: '<path d="M20 6 9 17l-5-5"/>', x: '<path d="M18 6 6 18M6 6l12 12"/>',
  message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  shuffle: '<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  party: '<path d="M5.8 11.3 2 22l10.7-3.8"/><path d="M4 3h.01M22 8h.01M15 2h.01M22 20h.01M22 2l-2.2.7a2.9 2.9 0 0 0-1.9 3.5c.4 1.4-.6 2.7-2 2.7H15"/><path d="m11 13 2-2"/>',
};
function icon(name) { return `<svg class="i" viewBox="0 0 24 24">${ICONS[name] || ''}</svg>`; }
function paintIcons(root = document) { root.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon); }); }

/* ---------- helpers ---------- */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function lsGet(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } }
async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
function nice(v) { return String(v).replace(/_/g, ' '); }
function personColor(name) { return PERSON_COLORS[Math.max(0, (S.config?.annotators || []).indexOf(name)) % PERSON_COLORS.length]; }
function toast(text, kind = '', ico = 'check') {
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.innerHTML = `${icon(ico)}<span>${esc(text)}</span>`;
  $('toasts').appendChild(t);
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 300); }, 2600);
}

/* ---------- theme ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  lsSet(LS.theme, t);
  $('btnTheme').dataset.icon = t === 'dark' ? 'sun' : 'moon';
  paintIcons($('btnTheme').parentElement);
}

/* ---------- identity ---------- */
function askWho(force) {
  if (S.who && !force) return Promise.resolve(S.who);
  return new Promise((resolve) => {
    const box = $('whoNames');
    box.innerHTML = '';
    S.config.annotators.forEach((n) => {
      const b = document.createElement('button');
      b.innerHTML = `<span class="avatar" style="background:${personColor(n)}">${esc(n[0].toUpperCase())}</span>${esc(n)}`;
      b.onclick = () => { $('whoDialog').classList.add('hidden'); resolve(n); };
      box.appendChild(b);
    });
    paintIcons($('whoDialog'));
    $('whoDialog').classList.remove('hidden');
  });
}

async function setWho(name) {
  S.who = name;
  lsSet(LS.who, name);
  $('who').textContent = name;
  $('avatar').textContent = name[0].toUpperCase();
  $('avatar').style.background = personColor(name);
  await flushQueue();
  await loadBatches();
  const pos = lsGet(LS.pos(name), {});
  const mine = S.batches.filter((b) => b.role);
  const start = mine.find((b) => b.batch_id === pos.batchId) || mine[0];
  if (start) await loadBatch(start.batch_id, pos.batchId === start.batch_id ? pos.idx : 0);
}

/* ---------- batches ---------- */
async function loadBatches() {
  S.batches = await api(`/api/batches?annotator=${S.who}`);
  renderBatchMenu();
}

function batchLabel(id) { return id.replace('batch_', 'Batch '); }

function renderBatchMenu() {
  const item = (b) => {
    const pct = b.total ? Math.round((100 * b.done) / b.total) : 0;
    return `<button class="b-item${b.batch_id === S.batchId ? ' on' : ''}" data-id="${b.batch_id}" ${b.role ? '' : 'disabled'}>` +
      `<b>${batchLabel(b.batch_id)}</b>` +
      (b.role ? `<span class="bar"><i style="width:${pct}%"></i></span><span class="num">${b.done}/${b.total}</span>`
        : '<span class="muted">not assigned</span><span></span>') + '</button>';
  };
  const groups = [['primary', 'Primary — label every case'], ['tiebreak', 'Tie-break — disputed cases only'], [null, 'Other batches']];
  $('batchMenu').innerHTML = groups.map(([role, title]) => {
    const list = S.batches.filter((b) => b.role === role);
    return list.length ? `<div class="group">${title}</div>${list.map(item).join('')}` : '';
  }).join('');
  $('batchMenu').querySelectorAll('.b-item:not(:disabled)').forEach((b) => {
    b.onclick = () => { toggleBatchMenu(false); loadBatch(b.dataset.id, 0); };
  });
}

function toggleBatchMenu(open) {
  const show = open ?? $('batchMenu').classList.contains('hidden');
  if (show) renderBatchMenu();
  $('batchMenu').classList.toggle('hidden', !show);
  document.querySelector('.batch-picker').classList.toggle('open', show);
}

async function loadBatch(batchId, idx = 0) {
  const d = await api(`/api/batch?id=${batchId}&annotator=${S.who}`);
  S.batchId = batchId; S.role = d.role; S.cases = d.cases; S.votes = d.votes; S.others = d.others;
  for (const q of lsGet(LS.queue(S.who), [])) {           // unsent local changes win over the server copy
    if (q.batch_id === batchId) { if (q.vote) S.votes[q.case_id] = q.vote; else delete S.votes[q.case_id]; }
  }
  $('batchName').textContent = batchLabel(batchId);
  $('roleChip').textContent = d.role === 'tiebreak' ? 'tie-break' : 'primary · blind';
  $('roleChip').className = `role ${d.role}`;
  $('othersWrap').classList.toggle('hidden', d.role !== 'tiebreak');
  go(Math.min(idx, Math.max(S.cases.length - 1, 0)));
}

/* ---------- navigation ---------- */
function complete(v) {
  if (!v || !v.gold_decision || !v.gold_final_action || !v.gold_missing_evidence || !v.gold_required_authority) return false;
  if (v.gold_decision !== 'ASK_USER') return true;
  const u = v.user_response || {};
  return !!(u.text || '').trim() && (u.confirmed === true || u.confirmed === false);
}
function go(i) {
  if (!S.cases.length) { renderEmpty(); return; }
  S.idx = (i + S.cases.length) % S.cases.length;
  lsSet(LS.pos(S.who), { batchId: S.batchId, idx: S.idx });
  render();
}
function nextIncomplete() {
  for (let k = 1; k <= S.cases.length; k++) {
    const j = (S.idx + k) % S.cases.length;
    if (!complete(S.votes[S.cases[j].case_id])) return go(j);
  }
  toast('Every case in this batch is complete', 'good', 'party');
}

/* ---------- rendering ---------- */
function isEmpty(v) {
  return v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length) ||
    (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length);
}
function val(v) { return esc(typeof v === 'object' ? JSON.stringify(v) : v); }
function trust(t) { return `<span class="t t-${esc(t || 'unknown')}">${esc(nice(t || 'unknown'))}</span>`; }
function lvl(l) { return `<span class="lvl ${l ? esc(l) : 'none'}">${esc(l || 'none')}</span>`; }

/* Authority facts: two per row, empty values hidden, booleans as coloured dots, lists as chips. */
function facts(obj) {
  if (!obj || typeof obj !== 'object') return '<span class="empty">—</span>';
  const cells = [];
  for (const [k, v] of Object.entries(obj)) {
    if (isEmpty(v)) continue;
    let html;
    let wide = false;
    if (typeof v === 'boolean') html = `<span class="${v ? 'dot-yes' : 'dot-no'}">${v ? 'yes' : 'no'}</span>`;
    else if (Array.isArray(v)) { html = v.map((x) => `<span class="chip-s">${val(x)}</span>`).join(''); wide = true; }
    else if (typeof v === 'object') { html = `<span class="chip-s">${esc(JSON.stringify(v))}</span>`; wide = true; }
    else { html = esc(v); wide = String(v).length > 26; }
    cells.push(`<div class="fact${wide ? ' wide' : ''}"><span class="k">${esc(nice(k))}</span><span class="v">${html}</span></div>`);
  }
  return cells.length ? `<div class="facts">${cells.join('')}</div>` : '<span class="empty">nothing recorded</span>';
}

function renderEmpty() {
  ['request', 'call', 'prior', 'resolution', 'authority', 'sensitivity', 'origin', 'untrusted', 'retrieved', 'grid', 'mix', 'caseMeta']
    .forEach((id) => { $(id).innerHTML = ''; });
  $('request').innerHTML = `<span class="empty">${S.role === 'tiebreak'
    ? 'No disputed cases in this batch yet — both primary annotators must finish and push their votes; then pull.'
    : 'No cases.'}</span>`;
  $('pos').textContent = '0 / 0';
  updateProgress();
}

function render() {
  const c = S.cases[S.idx];
  const inp = c.input || {};
  $('pos').textContent = `${S.idx + 1} / ${S.cases.length}`;
  $('caseMeta').innerHTML = `<span class="tag suite">${esc(c.suite)}</span><span class="tag">${esc(nice(c.category))}</span>` +
    `<span class="tag ${esc(c.difficulty)}">${esc(c.difficulty)}</span><span class="tag">round ${esc(c.round)}</span>` +
    `<span class="cid" title="${esc(c.case_id)}">${esc(c.case_id)}</span>`;
  $('request').textContent = (inp.user && inp.user.prompt) || '—';

  const call = inp.proposed_call || {};
  const prov = {};
  (inp.provenance || []).forEach((p) => { if (p.arg) prov[p.arg] = p; });
  const rows = Object.entries(call.args || {}).map(([k, v]) => {
    const p = prov[k] || {};
    const srcs = p.sources || [];
    const chips = srcs.map((s) => `<span class="src-chip${s === 'user_prompt' ? ' user' : ''}">${esc(s)}</span>`).join('') || '<span class="muted">—</span>';
    return `<tr data-src="${esc(srcs.filter((s) => /^T\d+$/.test(s)).join(' '))}"><td>${esc(k)}</td><td>${val(v)}</td>` +
      `<td>${chips}</td><td>${trust(p.trust)}</td></tr>`;
  });
  $('call').innerHTML = `<div class="fn"><code>${esc(call.function)}()</code>` +
    `${call.action ? `<span class="badge">${esc(call.action)}</span>` : ''}` +
    `${call.state_changing ? '<span class="badge warn">state-changing</span>' : ''}</div>` +
    `<table><thead><tr><th>arg</th><th>value</th><th>source</th><th>trust</th></tr></thead>` +
    `<tbody>${rows.join('') || '<tr><td colspan="4" class="empty">no arguments</td></tr>'}</tbody></table>`;

  const prior = inp.prior_calls || [];
  $('priorWrap').classList.toggle('hidden', !prior.length);
  $('prior').innerHTML = `<div class="prior">${prior.map((p, i) =>
    `<div><span class="n">${i + 1}</span><code>${esc(p.function)}</code><span>${val(p.args || {})}</span></div>`).join('')}</div>`;

  const res = inp.resolution_history || [];
  $('resWrap').classList.toggle('hidden', !res.length);
  $('resolution').innerHTML = res.map((r) => {
    const ok = r.kind === 'ESCALATE' ? r.approved : r.confirmed;
    const okTxt = r.kind === 'ESCALATE' ? 'approved' : 'confirmed';
    return `<div class="res"><span class="badge">round ${esc(r.round)}</span> <b>${esc(nice(r.kind))}</b> ` +
      `<span class="muted">asked ${esc(Object.values(r.asked || {}).map(nice).join(' · ') || '—')}</span>` +
      `<div class="who-line"><span class="chip-s">${esc(r.responder)}</span><q>${esc(r.response)}</q>` +
      `<span class="${ok === true ? 'dot-yes' : ok === false ? 'dot-no' : 'muted'}">${okTxt}: ${esc(ok)}</span></div></div>`;
  }).join('');

  $('authority').innerHTML = facts(inp.authority);
  const sens = inp.sensitivity || {};
  $('sensitivity').innerHTML = `<div class="flow">${lvl(sens.resource)}<span class="arrow">${icon('arrow')}</span>${lvl(sens.destination)}</div>` +
    `<div class="flow-state">flow <b class="${sens.flow === 'high_to_low' ? 'bad' : ''}">${esc(nice(sens.flow ?? '—'))}</b>` +
    `${(sens.basis || []).map((b) => `<span class="chip-s">${esc(b)}</span>`).join('')}</div>`;

  const origin = (inp.provenance || []).find((p) => p.kind === 'call');
  const bad = !!origin && origin.trust === 'untrusted';
  $('originCard').className = `card ${bad ? 'tone-red' : 'tone-green'}`;
  $('origin').innerHTML = origin
    ? `<div class="origin${bad ? ' bad' : ''}"><span class="big">${icon(bad ? 'alert' : 'shield')}</span>` +
      `<div><b>${esc(origin.instruction_origin)}</b>${origin.origin_source ? `<small>${esc(origin.origin_source)}</small>` : ''}` +
      `<div>${trust(origin.trust)}</div></div></div>`
    : '<span class="empty">—</span>';

  const untrusted = inp.untrusted_content || [];
  $('untrustedCount').textContent = untrusted.length ? `${untrusted.length} block${untrusted.length > 1 ? 's' : ''}` : '';
  $('untrustedCard').classList.toggle('has', untrusted.length > 0);
  $('untrusted').innerHTML = untrusted.map((u) =>
    `<div class="ublock" data-id="${esc(u.id)}"><div class="uh">${esc(u.id)}<span>${esc(u.source)}</span></div><pre>${esc(u.text)}</pre></div>`).join('') ||
    '<span class="empty">none</span>';
  $('retrieved').innerHTML = (inp.policy_clauses || []).map((cl) => clauseHtml(cl)).join('') || '<span class="empty">none</span>';
  $('rawText').textContent = c.case_text || '';

  if (S.role === 'tiebreak') {
    $('others').innerHTML = (S.others[c.case_id] || []).map((v) =>
      `<div class="res" style="background:color-mix(in srgb, ${DECISION_COLOR[v.gold_decision] || 'var(--slate)'} 10%, transparent)">` +
      `<span class="avatar" style="display:inline-grid;width:20px;height:20px;font-size:10px;background:${personColor(v.annotator)}">${esc(v.annotator[0].toUpperCase())}</span> ` +
      `<b>${esc(v.annotator)}</b> · <b>${esc(nice(v.gold_decision))}</b> → ${esc(v.gold_final_action)}` +
      ` <span class="muted">· ${esc(nice(v.gold_missing_evidence))} · ${esc(nice(v.gold_required_authority))}</span>` +
      (v.gold_clause_ids && v.gold_clause_ids.length ? `<div>${v.gold_clause_ids.map((x) => `<span class="chip-s">${esc(x)}</span>`).join('')}</div>` : '') +
      (v.user_response && v.user_response.text ? `<div class="who-line"><q>${esc(v.user_response.text)}</q> (${v.user_response.confirmed ? 'yes' : 'no'})</div>` : '') +
      (v.notes ? `<div class="muted">${esc(v.notes)}</div>` : '') + '</div>').join('');
  }

  document.querySelectorAll('#colCase .card, #colEvidence .card').forEach((el) => {
    el.classList.remove('swap'); void el.offsetWidth; el.classList.add('swap');
  });
  bindHovers();
  renderVote();
  renderGrid();
  updateProgress();
  bindCiteButtons();
}

/* hovering an argument highlights the tool output its value came from */
function bindHovers() {
  document.querySelectorAll('#call tbody tr[data-src]').forEach((tr) => {
    const ids = tr.dataset.src.split(' ').filter(Boolean);
    if (!ids.length) return;
    tr.onmouseenter = () => ids.forEach((id) => {
      const b = document.querySelector(`.ublock[data-id="${CSS.escape(id)}"]`);
      if (b) { b.classList.add('flash'); b.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    });
    tr.onmouseleave = () => document.querySelectorAll('.ublock.flash').forEach((b) => b.classList.remove('flash'));
  });
}

function clauseHtml(cl, hl) {
  const cited = (cur().gold_clause_ids || []).includes(cl.id);
  const text = hl ? highlight(cl.text, hl) : esc(cl.text);
  return `<div class="clause${cited ? ' cited' : ''}${hl ? ' open' : ''}" data-id="${esc(cl.id)}"><div class="ch">` +
    `<span class="cid">${esc(cl.id)}</span><span class="ct">${hl ? highlight(cl.title, hl) : esc(cl.title)}</span>` +
    `${cl.doc ? `<span class="doc">${esc(cl.doc)}</span>` : ''}` +
    `<button class="cite${cited ? ' on' : ''}" data-id="${esc(cl.id)}">${icon('bookmark')}${cited ? 'cited' : 'cite'}</button></div>` +
    `<div class="body">${text}</div></div>`;
}
function bindCiteButtons() {
  document.querySelectorAll('.cite').forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); toggleCite(b.dataset.id); };
  });
  document.querySelectorAll('.clause').forEach((d) => { d.onclick = () => d.classList.toggle('open'); });
}

function cur() { return S.votes[S.cases[S.idx]?.case_id] || {}; }

function renderChips(id, values, selected) {
  $(id).querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.v === selected));
}
function renderPills(name, value) {
  document.querySelectorAll(`.pills[data-name="${name}"] button`).forEach((b) => {
    b.classList.toggle('on', value !== undefined && ((b.dataset.v === 'yes' && value === true) ||
      (b.dataset.v === 'no' && value === false) || (b.dataset.v === 'none' && value === null)));
  });
}

function renderVote() {
  const v = cur();
  document.querySelectorAll('#decisionRow button').forEach((b) => b.classList.toggle('on', b.dataset.decision === v.gold_decision));
  const fixed = v.gold_decision === 'ALLOW' || v.gold_decision === 'BLOCK';
  const sw = $('finalRow');
  sw.classList.toggle('allow', v.gold_final_action === 'ALLOW');
  sw.classList.toggle('block', v.gold_final_action === 'BLOCK');
  sw.classList.toggle('locked', fixed);
  sw.querySelectorAll('button').forEach((b) => { b.disabled = fixed; });
  renderChips('missing', S.config.vocab.missing_evidence, v.gold_missing_evidence);
  renderChips('authorityReq', S.config.vocab.required_authority, v.gold_required_authority);
  const ask = v.gold_decision === 'ASK_USER';
  $('userReply').classList.toggle('hidden', !ask);
  const u = v.user_response || {};
  if (document.activeElement !== $('replyText')) $('replyText').value = u.text || '';
  renderPills('confirmed', u.confirmed);
  const noisy = u.noisy_text !== undefined && u.noisy_text !== null;
  $('noisyOn').checked = noisy;
  $('noisyWrap').classList.toggle('hidden', !noisy);
  if (document.activeElement !== $('noisyText')) $('noisyText').value = u.noisy_text || '';
  renderPills('noisyConfirmed', noisy ? u.noisy_confirmed : undefined);
  const ids = v.gold_clause_ids || [];
  $('cited').innerHTML = ids.length ? ids.map((id) => `<span class="tag">${esc(id)}<button data-id="${esc(id)}" title="remove">×</button></span>`).join('')
    : '<span class="empty">none yet — use cite on a clause</span>';
  $('cited').querySelectorAll('button').forEach((b) => { b.onclick = () => toggleCite(b.dataset.id); });
  if (document.activeElement !== $('notes')) $('notes').value = v.notes || '';
  const st = !v.gold_decision ? ['none', 'not labelled'] : complete(v) ? ['done', '✓ complete'] : ['part', 'incomplete'];
  $('voteState').className = `state ${st[0]}`;
  $('voteState').textContent = st[1];
}

function renderGrid() {
  const counts = { ALLOW: 0, BLOCK: 0, ASK_USER: 0, ESCALATE: 0, partial: 0 };
  $('grid').innerHTML = S.cases.map((c, i) => {
    const v = S.votes[c.case_id];
    const done = complete(v);
    if (done) counts[v.gold_decision] += 1; else if (v && v.gold_decision) counts.partial += 1;
    const cls = done ? `d-${v.gold_decision}` : v && v.gold_decision ? 'partial' : '';
    const tip = v && v.gold_decision ? `${nice(v.gold_decision)}${done ? ` → ${v.gold_final_action}` : ' (incomplete)'}` : 'not labelled';
    return `<button class="${cls}${i === S.idx ? ' current' : ''}" data-i="${i}" title="case ${i + 1}: ${tip}">${i + 1}</button>`;
  }).join('');
  $('grid').querySelectorAll('button').forEach((b) => { b.onclick = () => go(+b.dataset.i); });
  const sw = (color, label, n) => `<span><i style="background:${color}"></i>${label} <b>${n}</b></span>`;
  $('mix').innerHTML = sw('var(--allow)', 'allow', counts.ALLOW) + sw('var(--block)', 'block', counts.BLOCK) +
    sw('var(--ask)', 'ask', counts.ASK_USER) + sw('var(--esc)', 'escalate', counts.ESCALATE) +
    sw('color-mix(in srgb, var(--amber) 40%, transparent)', 'incomplete', counts.partial);
}

function updateProgress() {
  const done = S.cases.filter((c) => complete(S.votes[c.case_id])).length;
  const n = S.cases.length;
  const pct = n ? done / n : 0;
  $('progress').textContent = `${done} of ${n} complete`;
  $('progressFill').style.width = `${100 * pct}%`;
  $('ring').style.strokeDashoffset = String(97.4 * (1 - pct));
  $('ring').style.stroke = pct === 1 ? 'var(--allow)' : 'var(--accent)';
  const b = S.batches.find((x) => x.batch_id === S.batchId);
  if (b) {
    const before = b.done;
    b.done = done;
    if (n && done === n && before < n) toast(`${batchLabel(S.batchId)} complete — commit and push your votes`, 'good', 'party');
  }
}

/* ---------- editing + saving ---------- */
function edit(patch) {
  const c = S.cases[S.idx];
  if (!c) return;
  const v = { ...cur(), ...patch };
  S.votes[c.case_id] = v;
  enqueue(c.case_id, v);
  renderVote();
  renderGrid();
  updateProgress();
}

function setDecision(d) {
  const [m, a] = DEFAULTS[d];
  const v = cur();
  const patch = { gold_decision: d, gold_missing_evidence: m, gold_required_authority: a };
  patch.gold_final_action = (d === 'ALLOW' || d === 'BLOCK') ? d : (v.gold_decision === d ? v.gold_final_action : null);
  if (d !== 'ASK_USER') patch.user_response = null;
  edit(patch);
}

function editReply(patch) { edit({ user_response: { ...(cur().user_response || {}), ...patch } }); }

function toggleCite(id) {
  const ids = new Set(cur().gold_clause_ids || []);
  if (ids.has(id)) ids.delete(id); else ids.add(id);
  edit({ gold_clause_ids: [...ids].sort() });
  const on = ids.has(id);
  document.querySelectorAll(`.cite[data-id="${CSS.escape(id)}"]`).forEach((b) => {
    b.classList.toggle('on', on);
    b.innerHTML = `${icon('bookmark')}${on ? 'cited' : 'cite'}`;
  });
  document.querySelectorAll(`.clause[data-id="${CSS.escape(id)}"]`).forEach((d) => d.classList.toggle('cited', on));
}

function clearVote() {
  const c = S.cases[S.idx];
  if (!c || !S.votes[c.case_id] || !confirm('Delete your vote on this case?')) return;
  delete S.votes[c.case_id];
  enqueue(c.case_id, null);
  render();
  toast('Vote cleared', '', 'trash');
}

function enqueue(caseId, vote) {
  const q = lsGet(LS.queue(S.who), []).filter((x) => !(x.batch_id === S.batchId && x.case_id === caseId));
  q.push({ batch_id: S.batchId, case_id: caseId, vote });
  lsSet(LS.queue(S.who), q);
  setSave('saving…');
  clearTimeout(enqueue.t);
  enqueue.t = setTimeout(flushQueue, 300);
}

async function flushQueue() {
  if (!S.who || S.sending) return;
  S.sending = true;
  try {
    let q = lsGet(LS.queue(S.who), []);
    if (!q.length) { setSave('all saved'); return; }
    while (q.length) {
      const item = q[0];
      try {
        await api('/api/vote', { annotator: S.who, ...item });
      } catch (e) {
        if (e instanceof TypeError) { setSave('offline — kept in this browser, will retry'); setTimeout(flushQueue, 5000); return; }
        setSave(`not saved: ${e.message}`);                // rejected by the server: drop it, keep going
        toast(`Not saved: ${e.message}`, 'bad', 'alert');
      }
      q = lsGet(LS.queue(S.who), []);
      const i = q.findIndex((x) => x.batch_id === item.batch_id && x.case_id === item.case_id && JSON.stringify(x.vote) === JSON.stringify(item.vote));
      if (i >= 0) q.splice(i, 1);
      lsSet(LS.queue(S.who), q);
    }
    if (!$('saveState').textContent.startsWith('not saved')) setSave(`saved ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`);
  } finally {
    S.sending = false;
  }
}
function setSave(t) {
  const el = $('saveState');
  el.querySelector('span').textContent = t;
  el.title = t;
  el.className = 'save ' + (t.startsWith('saved') || t === 'all saved' ? 'ok'
    : t.startsWith('saving') ? 'busy' : t.startsWith('not saved') || t.startsWith('offline') ? 'err' : '');
}

/* ---------- policy search ---------- */
function highlight(text, terms) {
  let out = esc(text);
  for (const t of terms) out = out.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>');
  return out;
}
function search() {
  const terms = $('q').value.toLowerCase().split(/\s+/).filter((t) => t.length > 1);
  if (!terms.length) {                                   // no query: browse every clause, grouped by document
    const docs = [...new Set(S.policies.map((p) => p.doc))];
    $('results').innerHTML = docs.map((d) => `<div class="doc-head">${esc(d)}</div>` +
      S.policies.filter((p) => p.doc === d).map((p) => clauseHtml(p)).join('')).join('') ||
      '<span class="empty">No policy documents found in resources/handbooks/.</span>';
    bindCiteButtons();
    return;
  }
  const scored = S.policies.map((p) => {
    const hay = `${p.id} ${p.title} ${p.title} ${p.text}`.toLowerCase();
    const s = terms.reduce((n, t) => n + (hay.split(t).length - 1), 0);
    return { p, s, all: terms.every((t) => hay.includes(t)) };
  }).filter((x) => x.s > 0).sort((a, b) => (b.all - a.all) || (b.s - a.s));
  $('results').innerHTML = scored.slice(0, 40).map((x) => clauseHtml(x.p, terms)).join('') || '<span class="empty">no match</span>';
  bindCiteButtons();
}

/* ---------- wiring ---------- */
function openDrawer(open = true) {
  $('drawer').classList.toggle('hidden', !open);
  if (open) { search(); $('q').focus(); $('q').select(); }
}

function buildChips(id, values, field) {
  $(id).innerHTML = values.map((v) => `<button data-v="${v}">${nice(v)}</button>`).join('');
  $(id).querySelectorAll('button').forEach((b) => { b.onclick = () => edit({ [field]: b.dataset.v }); });
}

function wire() {
  paintIcons();
  buildChips('missing', S.config.vocab.missing_evidence, 'gold_missing_evidence');
  buildChips('authorityReq', S.config.vocab.required_authority, 'gold_required_authority');

  $('btnWho').onclick = async () => {
    if (!confirm('Switch annotator? Votes stay saved under each name.')) return;
    await setWho(await askWho(true));
  };
  $('batchBtn').onclick = (e) => { e.stopPropagation(); toggleBatchMenu(); };
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.batch-picker')) toggleBatchMenu(false);
    if (e.target.classList.contains('overlay') && e.target.id === 'helpDialog') e.target.classList.add('hidden');
  });
  $('btnPrev').onclick = () => go(S.idx - 1);
  $('btnNext').onclick = () => go(S.idx + 1);
  $('btnUnlabeled').onclick = nextIncomplete;
  $('btnRaw').onclick = () => {
    S.raw = !S.raw;
    $('colRaw').classList.toggle('hidden', !S.raw);
    $('colCase').classList.toggle('hidden', S.raw);
    $('colEvidence').classList.toggle('hidden', S.raw);
    $('btnRaw').classList.toggle('on', S.raw);
  };
  $('btnTheme').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  $('btnHelp').onclick = () => $('helpDialog').classList.remove('hidden');
  document.querySelectorAll('#decisionRow button').forEach((b) => { b.onclick = () => setDecision(b.dataset.decision); });
  document.querySelectorAll('#finalRow button').forEach((b) => { b.onclick = () => edit({ gold_final_action: b.dataset.final }); });
  $('replyText').oninput = (e) => editReply({ text: e.target.value });
  document.querySelectorAll('.pills[data-name="confirmed"] button').forEach((b) => { b.onclick = () => editReply({ confirmed: b.dataset.v === 'yes' }); });
  $('noisyOn').onchange = (e) => editReply(e.target.checked ? { noisy_text: '', noisy_confirmed: null } : { noisy_text: null, noisy_confirmed: null });
  $('noisyText').oninput = (e) => editReply({ noisy_text: e.target.value });
  document.querySelectorAll('.pills[data-name="noisyConfirmed"] button').forEach((b) => {
    b.onclick = () => editReply({ noisy_confirmed: b.dataset.v === 'none' ? null : b.dataset.v === 'yes' });
  });
  $('notes').oninput = (e) => edit({ notes: e.target.value });
  $('btnClear').onclick = clearVote;
  $('btnPolicy').onclick = () => openDrawer(true);
  $('btnCloseDrawer').onclick = () => openDrawer(false);
  $('drawer').onclick = (e) => { if (e.target.id === 'drawer') openDrawer(false); };
  $('q').oninput = search;
  $('policyCount').textContent = `${S.policies.length} clauses · ${new Set(S.policies.map((p) => p.doc)).size} documents · click to expand, cite adds to your vote`;

  document.addEventListener('keydown', (e) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    if (e.key === 'Escape') {
      if (typing) document.activeElement.blur();
      toggleBatchMenu(false);
      openDrawer(false);
      $('helpDialog').classList.add('hidden');
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    const d = { 1: 'ALLOW', 2: 'BLOCK', 3: 'ASK_USER', 4: 'ESCALATE' }[e.key];
    if (d) setDecision(d);
    else if (e.key === 'ArrowRight' || e.key === 'Enter') go(S.idx + 1);
    else if (e.key === 'ArrowLeft') go(S.idx - 1);
    else if (e.key === 'u' || e.key === 'U') nextIncomplete();
    else if (e.key === 'r' || e.key === 'R') $('btnRaw').click();
    else if (e.key === 'b' || e.key === 'B') toggleBatchMenu();
    else if (e.key === 'd' || e.key === 'D') $('btnTheme').click();
    else if (e.key === '?') $('helpDialog').classList.remove('hidden');
    else if (e.key === '/') openDrawer(true);
    else return;
    e.preventDefault();
  });
  window.addEventListener('online', flushQueue);
}

(async function init() {
  setTheme(lsGet(LS.theme, matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  S.config = await api('/api/config');
  S.policies = await api('/api/policies');
  wire();
  // a saved name wins; ?annotator=<name> only preselects it on a first visit
  const saved = lsGet(LS.who, null) || new URLSearchParams(location.search).get('annotator');
  await setWho(S.config.annotators.includes(saved) ? saved : await askWho(true));
})();
