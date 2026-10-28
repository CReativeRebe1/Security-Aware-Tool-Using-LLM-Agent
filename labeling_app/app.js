/* Labelling tool. Every change is saved at once: first to this browser (localStorage queue), then to the local
   server, which writes your own vote file. Unsent changes are re-sent on the next load. */

const $ = (id) => document.getElementById(id);
const S = {
  who: null, config: null, batches: [], batchId: null, role: null,
  cases: [], votes: {}, others: {}, idx: 0, policies: [], raw: false, sending: false,
};
const LS = { who: 'labeler.who', pos: (w) => `labeler.pos.${w}`, queue: (w) => `labeler.queue.${w}` };

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
const DEFAULTS = {
  ALLOW: ['none', 'current_user'], BLOCK: ['none', 'none'],
  ASK_USER: ['user_intent', 'current_user'], ESCALATE: ['approval', 'manager'],
};

/* ---------- identity ---------- */
function askWho(force) {
  if (S.who && !force) return Promise.resolve(S.who);
  return new Promise((resolve) => {
    const box = $('whoNames');
    box.innerHTML = '';
    S.config.annotators.forEach((n) => {
      const b = document.createElement('button');
      b.textContent = n;
      b.onclick = () => { $('whoDialog').classList.add('hidden'); resolve(n); };
      box.appendChild(b);
    });
    $('whoDialog').classList.remove('hidden');
  });
}

async function setWho(name) {
  S.who = name;
  lsSet(LS.who, name);
  $('who').textContent = name;
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
  const sel = $('batchSelect');
  sel.innerHTML = '';
  for (const b of S.batches) {
    const o = document.createElement('option');
    o.value = b.batch_id;
    const n = b.batch_id.replace('batch_', 'Batch ');
    o.textContent = b.role ? `${n} · ${b.role} · ${b.done}/${b.total}` : `${n} · not assigned`;
    o.disabled = !b.role;
    sel.appendChild(o);
  }
  if (S.batchId) sel.value = S.batchId;
}

async function loadBatch(batchId, idx = 0) {
  const d = await api(`/api/batch?id=${batchId}&annotator=${S.who}`);
  S.batchId = batchId; S.role = d.role; S.cases = d.cases; S.votes = d.votes; S.others = d.others;
  for (const q of lsGet(LS.queue(S.who), [])) {           // unsent local changes win over the server copy
    if (q.batch_id === batchId) { if (q.vote) S.votes[q.case_id] = q.vote; else delete S.votes[q.case_id]; }
  }
  $('batchSelect').value = batchId;
  $('roleChip').textContent = d.role === 'tiebreak' ? 'tie-break: disputed cases only' : 'primary · blind';
  $('roleChip').className = `chip ${d.role}`;
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
}

/* ---------- rendering ---------- */
function isEmpty(v) {
  return v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length) ||
    (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length);
}
/* Compact facts: two per row, empty values hidden, booleans coloured, lists as pills, long values span the row. */
function kv(obj) {
  if (!obj || typeof obj !== 'object') return '<span class="empty">—</span>';
  const cells = [];
  for (const [k, v] of Object.entries(obj)) {
    if (isEmpty(v)) continue;
    let html;
    let wide = false;
    if (typeof v === 'boolean') html = `<span class="${v ? 'yes' : 'no'}">${v ? 'yes' : 'no'}</span>`;
    else if (Array.isArray(v)) { html = v.map((x) => `<span class="pill">${val(x)}</span>`).join(''); wide = true; }
    else if (typeof v === 'object') { html = esc(JSON.stringify(v)); wide = true; }
    else { html = esc(v); wide = String(v).length > 28; }
    cells.push(`<div class="pair${wide ? ' wide' : ''}"><span class="k">${esc(k)}</span> <span class="v">${html}</span></div>`);
  }
  return cells.length ? `<div class="kv">${cells.join('')}</div>` : '<span class="empty">nothing recorded</span>';
}
function trust(t) { return `<span class="t t-${esc(t || 'unknown')}">${esc(t || 'unknown')}</span>`; }
function val(v) { return esc(typeof v === 'object' ? JSON.stringify(v) : v); }

function renderEmpty() {
  ['request', 'call', 'prior', 'resolution', 'authority', 'sensitivity', 'origin', 'untrusted', 'retrieved', 'grid']
    .forEach((id) => { $(id).innerHTML = ''; });
  $('request').innerHTML = `<span class="empty">${S.role === 'tiebreak'
    ? 'No disputed cases in this batch yet (both primary annotators must finish their votes, then pull).'
    : 'No cases.'}</span>`;
  $('pos').textContent = '0 / 0';
  updateProgress();
}

function render() {
  const c = S.cases[S.idx];
  const inp = c.input || {};
  $('pos').textContent = `${S.idx + 1} / ${S.cases.length}`;
  $('caseMeta').innerHTML = `<b>${esc(c.suite)}</b> · <b>${esc(c.category)}</b> · ${esc(c.difficulty)} · round ${esc(c.round)}` +
    ` · <span title="case id">${esc(c.case_id)}</span>`;
  $('request').textContent = (inp.user && inp.user.prompt) || '—';

  const call = inp.proposed_call || {};
  const prov = {};
  (inp.provenance || []).forEach((p) => { if (p.arg) prov[p.arg] = p; });
  const rows = Object.entries(call.args || {}).map(([k, v]) => {
    const p = prov[k] || {};
    return `<tr><td>${esc(k)}</td><td>${val(v)}</td><td>${esc((p.sources || []).join(', ') || '—')}</td>` +
      `<td>${trust(p.trust)}</td></tr>`;
  });
  $('call').innerHTML = `<div class="fn">${esc(call.function)}() <span class="muted">${esc(call.action || '')}` +
    `${call.state_changing ? ' · state-changing' : ''}</span></div>` +
    `<table><tr><th>arg</th><th>value</th><th>source</th><th>trust</th></tr>${rows.join('') || '<tr><td colspan="4">no arguments</td></tr>'}</table>`;

  const prior = inp.prior_calls || [];
  $('priorWrap').classList.toggle('hidden', !prior.length);
  $('prior').innerHTML = prior.map((p, i) => `<div><span class="fn">${i + 1}. ${esc(p.function)}</span> ${val(p.args || {})}</div>`).join('');

  const res = inp.resolution_history || [];
  $('resWrap').classList.toggle('hidden', !res.length);
  $('resolution').innerHTML = res.map((r) => `<div class="res">round ${esc(r.round)} · ${esc(r.kind)} asked ${val(r.asked || {})}<br>` +
    `${esc(r.responder)}: "${esc(r.response)}"` +
    (r.kind === 'ESCALATE' ? ` · approved: ${esc(r.approved)}` : ` · confirmed: ${esc(r.confirmed)}`) + '</div>').join('');

  $('authority').innerHTML = kv(inp.authority);
  const sens = inp.sensitivity || {};
  const high = (l) => (l === 'CONFIDENTIAL' || l === 'RESTRICTED' ? ' hi' : '');
  $('sensitivity').innerHTML = `<div class="flow"><span class="pill${high(sens.resource)}">${esc(sens.resource ?? '—')}</span>` +
    `<span class="arrow">→</span><span class="pill">${esc(sens.destination ?? '—')}</span></div>` +
    `<div class="flow">flow: <b class="${sens.flow === 'high_to_low' ? 'no' : ''}">${esc(sens.flow ?? '—')}</b></div>` +
    ((sens.basis || []).length ? `<div class="flow">${sens.basis.map((b) => `<span class="pill">${esc(b)}</span>`).join('')}</div>` : '');
  const origin = (inp.provenance || []).find((p) => p.kind === 'call');
  document.querySelector('.c-origin').classList.toggle('bad', !!origin && origin.trust === 'untrusted');
  $('origin').innerHTML = origin ? `<div>${esc(origin.instruction_origin)}</div>` +
    `${origin.origin_source ? `<div class="doc">${esc(origin.origin_source)}</div>` : ''}${trust(origin.trust)}` : '<span class="empty">—</span>';
  const untrusted = inp.untrusted_content || [];
  $('untrustedCount').textContent = untrusted.length ? `${untrusted.length} block${untrusted.length > 1 ? 's' : ''}` : '';
  document.querySelector('.c-untrusted').classList.toggle('has', untrusted.length > 0);
  $('untrusted').innerHTML = untrusted.map((u) =>
    `<div class="untrusted"><div class="src">${esc(u.id)} · ${esc(u.source)}</div><pre>${esc(u.text)}</pre></div>`).join('') ||
    '<span class="empty">none</span>';
  $('retrieved').innerHTML = (inp.policy_clauses || []).map((cl) => clauseHtml(cl)).join('') || '<span class="empty">none</span>';
  $('rawText').textContent = c.case_text || '';

  if (S.role === 'tiebreak') {
    $('others').innerHTML = (S.others[c.case_id] || []).map((v) =>
      `<div class="other"><b>${esc(v.annotator)}</b>: ${esc(v.gold_decision)} → ${esc(v.gold_final_action)} · ` +
      `${esc(v.gold_missing_evidence)} / ${esc(v.gold_required_authority)}` +
      (v.gold_clause_ids && v.gold_clause_ids.length ? ` · ${esc(v.gold_clause_ids.join(', '))}` : '') +
      (v.user_response && v.user_response.text ? `<br>reply: "${esc(v.user_response.text)}" (${v.user_response.confirmed ? 'yes' : 'no'})` : '') +
      (v.notes ? `<br><span class="empty">${esc(v.notes)}</span>` : '') + '</div>').join('');
  }
  renderVote();
  renderGrid();
  updateProgress();
  bindCiteButtons();
}

function clauseHtml(cl, hl) {
  const cited = (cur().gold_clause_ids || []).includes(cl.id);
  const text = hl ? highlight(cl.text, hl) : esc(cl.text);
  return `<div class="clause${cited ? ' cited' : ''}${hl ? ' open' : ''}" data-id="${esc(cl.id)}">` +
    `<span class="id">${esc(cl.id)}</span> ${hl ? highlight(cl.title, hl) : esc(cl.title)} ` +
    `<button class="link cite" data-id="${esc(cl.id)}">${cited ? '✓ cited' : '+ cite'}</button>` +
    `${cl.doc ? ` <span class="doc">${esc(cl.doc)}</span>` : ''}<div class="body">${text}</div></div>`;
}
function bindCiteButtons() {
  document.querySelectorAll('.cite').forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); toggleCite(b.dataset.id); };
  });
  document.querySelectorAll('.clause').forEach((d) => { d.onclick = () => d.classList.toggle('open'); });
}

function cur() { return S.votes[S.cases[S.idx]?.case_id] || {}; }

function renderVote() {
  const v = cur();
  document.querySelectorAll('#decisionRow button').forEach((b) => b.classList.toggle('on', b.dataset.decision === v.gold_decision));
  const fixed = v.gold_decision === 'ALLOW' || v.gold_decision === 'BLOCK';
  document.querySelectorAll('#finalRow button').forEach((b) => {
    b.classList.toggle('on', b.dataset.final === v.gold_final_action);
    b.disabled = fixed;
  });
  $('missing').value = v.gold_missing_evidence || '';
  $('authorityReq').value = v.gold_required_authority || '';
  const ask = v.gold_decision === 'ASK_USER';
  $('userReply').classList.toggle('hidden', !ask);
  const u = v.user_response || {};
  $('replyText').value = u.text || '';
  document.querySelectorAll('input[name=confirmed]').forEach((r) => {
    r.checked = (r.value === 'yes' && u.confirmed === true) || (r.value === 'no' && u.confirmed === false);
  });
  const noisy = u.noisy_text !== undefined && u.noisy_text !== null;
  $('noisyOn').checked = noisy;
  $('noisyWrap').classList.toggle('hidden', !noisy);
  $('noisyText').value = u.noisy_text || '';
  document.querySelectorAll('input[name=noisyConfirmed]').forEach((r) => {
    r.checked = noisy && ((r.value === 'yes' && u.noisy_confirmed === true) || (r.value === 'no' && u.noisy_confirmed === false) ||
      (r.value === 'none' && u.noisy_confirmed === null));
  });
  const ids = v.gold_clause_ids || [];
  $('cited').innerHTML = ids.length ? ids.map((id) => `<span class="tag">${esc(id)}<button data-id="${esc(id)}" title="remove">×</button></span>`).join('')
    : '<span class="empty">none — use + cite on a clause</span>';
  $('cited').querySelectorAll('button').forEach((b) => { b.onclick = () => toggleCite(b.dataset.id); });
  $('notes').value = v.notes || '';
  const st = !v.gold_decision ? ['none', 'not labelled'] : complete(v) ? ['done', '✓ complete'] : ['part', 'incomplete'];
  $('voteState').className = `state ${st[0]}`;
  $('voteState').textContent = st[1];
}

function renderGrid() {
  $('grid').innerHTML = S.cases.map((c, i) => {
    const v = S.votes[c.case_id];
    const cls = complete(v) ? `d-${v.gold_decision}` : v && v.gold_decision ? 'partial' : '';
    const tip = v && v.gold_decision ? `${v.gold_decision}${complete(v) ? ` → ${v.gold_final_action}` : ' (incomplete)'}` : 'not labelled';
    return `<button class="${cls}${i === S.idx ? ' current' : ''}" data-i="${i}" title="case ${i + 1}: ${tip}">${i + 1}</button>`;
  }).join('');
  $('grid').querySelectorAll('button').forEach((b) => { b.onclick = () => go(+b.dataset.i); });
}

function updateProgress() {
  const done = S.cases.filter((c) => complete(S.votes[c.case_id])).length;
  $('progress').textContent = `${done} / ${S.cases.length} complete`;
  $('progressFill').style.width = S.cases.length ? `${(100 * done) / S.cases.length}%` : '0';
  const opt = $('batchSelect').selectedOptions[0];
  const b = S.batches.find((x) => x.batch_id === S.batchId);
  if (opt && b) opt.textContent = `${b.batch_id.replace('batch_', 'Batch ')} · ${b.role} · ${done}/${S.cases.length}`;
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
  document.querySelectorAll(`.cite[data-id="${CSS.escape(id)}"]`).forEach((b) => { b.textContent = ids.has(id) ? '✓ cited' : '+ cite'; });
  document.querySelectorAll(`.clause[data-id="${CSS.escape(id)}"]`).forEach((d) => d.classList.toggle('cited', ids.has(id)));
}

function clearVote() {
  const c = S.cases[S.idx];
  if (!c || !S.votes[c.case_id] || !confirm('Delete your vote on this case?')) return;
  delete S.votes[c.case_id];
  enqueue(c.case_id, null);
  render();
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
      }
      q = lsGet(LS.queue(S.who), []);
      const i = q.findIndex((x) => x.batch_id === item.batch_id && x.case_id === item.case_id && JSON.stringify(x.vote) === JSON.stringify(item.vote));
      if (i >= 0) q.splice(i, 1);
      lsSet(LS.queue(S.who), q);
    }
    if (!$('saveState').textContent.startsWith('not saved')) setSave(`saved ${new Date().toLocaleTimeString()}`);
  } finally {
    S.sending = false;
  }
}
function setSave(t) {
  $('saveState').textContent = t;
  $('saveState').className = 'save ' + (t.startsWith('saved') || t === 'all saved' ? 'ok'
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
  if (!terms.length) {
    $('results').innerHTML = `<span class="empty">${S.policies.length} clauses. Type to search ids, titles and text.</span>`;
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
function tab(name) {
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  $('tabGrid').classList.toggle('hidden', name !== 'grid');
  $('tabSearch').classList.toggle('hidden', name !== 'search');
  if (name === 'search') { $('q').focus(); search(); }
}

function wire() {
  const fill = (sel, vals) => { $(sel).innerHTML = '<option value=""></option>' + vals.map((v) => `<option>${v}</option>`).join(''); };
  fill('missing', S.config.vocab.missing_evidence);
  fill('authorityReq', S.config.vocab.required_authority);

  $('btnWho').onclick = async () => {
    if (!confirm('Switch annotator? Votes stay saved under each name.')) return;
    await setWho(await askWho(true));
  };
  $('batchSelect').onchange = (e) => loadBatch(e.target.value, 0);
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
  document.querySelectorAll('#decisionRow button').forEach((b) => { b.onclick = () => setDecision(b.dataset.decision); });
  document.querySelectorAll('#finalRow button').forEach((b) => { b.onclick = () => edit({ gold_final_action: b.dataset.final }); });
  $('missing').onchange = (e) => edit({ gold_missing_evidence: e.target.value || null });
  $('authorityReq').onchange = (e) => edit({ gold_required_authority: e.target.value || null });
  $('replyText').oninput = (e) => editReply({ text: e.target.value });
  document.querySelectorAll('input[name=confirmed]').forEach((r) => { r.onchange = () => editReply({ confirmed: r.value === 'yes' }); });
  $('noisyOn').onchange = (e) => editReply(e.target.checked ? { noisy_text: '', noisy_confirmed: null } : { noisy_text: null, noisy_confirmed: null });
  $('noisyText').oninput = (e) => editReply({ noisy_text: e.target.value });
  document.querySelectorAll('input[name=noisyConfirmed]').forEach((r) => {
    r.onchange = () => editReply({ noisy_confirmed: r.value === 'none' ? null : r.value === 'yes' });
  });
  $('notes').oninput = (e) => edit({ notes: e.target.value });
  $('btnClear').onclick = clearVote;
  document.querySelectorAll('#tabs button').forEach((b) => { b.onclick = () => tab(b.dataset.tab); });
  $('q').oninput = search;

  document.addEventListener('keydown', (e) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    if (typing) { if (e.key === 'Escape') document.activeElement.blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const d = { 1: 'ALLOW', 2: 'BLOCK', 3: 'ASK_USER', 4: 'ESCALATE' }[e.key];
    if (d) setDecision(d);
    else if (e.key === 'ArrowRight' || e.key === 'Enter') go(S.idx + 1);
    else if (e.key === 'ArrowLeft') go(S.idx - 1);
    else if (e.key === 'u' || e.key === 'U') nextIncomplete();
    else if (e.key === 'r' || e.key === 'R') $('btnRaw').click();
    else if (e.key === '/') { e.preventDefault(); tab('search'); }
    else return;
    e.preventDefault();
  });
  window.addEventListener('online', flushQueue);
}

(async function init() {
  S.config = await api('/api/config');
  S.policies = await api('/api/policies');
  wire();
  // a saved name wins; ?annotator=<name> only preselects it on a first visit
  const saved = lsGet(LS.who, null) || new URLSearchParams(location.search).get('annotator');
  await setWho(S.config.annotators.includes(saved) ? saved : await askWho(true));
})();
