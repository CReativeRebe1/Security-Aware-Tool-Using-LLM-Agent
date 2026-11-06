const $ = (id) => document.getElementById(id);
const S = { who: null, cfg: null, sug: {}, batch: null, cases: [], votes: {}, i: 0, mode: 'view', evidence: false,
  draft: null, busy: false };
const KEY = { who: 'labeler.who', pos: (w) => `labeler.pos.${w}` };
const DEF = { ALLOW: ['none', 'current_user'], BLOCK: ['none', 'none'], ASK_USER: ['user_intent', 'current_user'], ESCALATE: ['approval', 'manager'] };
const REASONS = [
  ['unclear_request', 'Request is unclear'],
  ['evidence_missing', 'Evidence is missing or broken'],
  ['evidence_conflict', 'Evidence contradicts itself'],
  ['no_option_fits', 'None of the 4 decisions fits'],
  ['not_security_case', 'Not a security decision'],
  ['bad_case', 'Duplicate or broken case'],
  ['other', 'Other'],
];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nice = (s) => String(s ?? '').replace(/_/g, ' ');
const get = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const put = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}
function toast(t) { const el = document.createElement('div'); el.className = 'toast'; el.textContent = t; document.body.appendChild(el); setTimeout(() => el.remove(), 2200); }
const cur = () => S.cases[S.i];
const sug = () => S.sug[cur()?.case_id] || null;
const mine = () => S.votes[cur()?.case_id] || null;
const status = (v) => v?.review?.status || null;

/* ---------- people & batches ---------- */
function pickWho() {
  return new Promise((res) => {
    $('people').innerHTML = S.cfg.annotators.map((n) => `<button data-n="${n}">${n}</button>`).join('');
    $('people').querySelectorAll('button').forEach((b) => { b.onclick = () => { $('whoDlg').classList.add('hidden'); res(b.dataset.n); }; });
    $('whoDlg').classList.remove('hidden');
  });
}
async function setWho(n) {
  S.who = n; put(KEY.who, n);
  $('who').textContent = n; $('avatar').textContent = n[0].toUpperCase();
  const batches = await api(`/api/batches?annotator=${n}`);
  const own = batches.filter((b) => b.reviewer);
  $('batch').innerHTML = own.map((b) =>
    `<option value="${b.batch_id}">${b.batch_id.replace('batch_', 'Batch ')} · ${b.done}/${b.total}</option>`).join('');
  const pos = get(KEY.pos(n), {});
  const first = own.find((b) => b.batch_id === pos.batch) || own[0];
  if (first) await loadBatch(first.batch_id, pos.batch === first.batch_id ? pos.i : 0);
  else toast('No batches are assigned to you');
}
async function loadBatch(id, i = 0) {
  const [d, sg] = await Promise.all([api(`/api/batch?id=${id}&annotator=${S.who}`),
    api(`/api/suggestions?id=${id}&annotator=${S.who}`)]);
  Object.assign(S, { batch: id, cases: d.cases, votes: d.votes, sug: sg });
  $('batch').value = id; $('role').textContent = 'review';
  go(Math.min(i, Math.max(S.cases.length - 1, 0)), true);
}

/* ---------- case card ---------- */
function signals(inp) {
  const prov = inp.provenance || [];
  const origin = prov.find((p) => p.kind === 'call') || {};
  const args = prov.filter((p) => p.kind === 'arg');
  const bad = args.filter((p) => p.trust === 'untrusted').length;
  const third = args.filter((p) => p.trust === 'third_party').length;
  const a = inp.authority || {}, s = inp.sensitivity || {};
  const role = a.required_role || a.required_authority;
  return [
    origin.trust === 'untrusted' ? ['bad', 'Origin', 'Injected', `from ${origin.instruction_origin || 'content'}`] : ['ok', 'Origin', 'The user', 'request came from the user'],
    a.user_may_authorize === false ? ['mid', 'Authority', nice(role || 'higher role'), (a.basis || []).map(nice).join(', ') || 'user cannot authorize'] : ['ok', 'Authority', 'User may act', nice(role || 'current user')],
    s.flow === 'high_to_low' ? ['bad', 'Data flow', 'High → low', `${s.resource} → ${s.destination}`] : ['info', 'Data flow', s.resource || '—', s.destination ? `to ${s.destination}` : 'no outgoing data'],
    bad ? ['bad', 'Arguments', `${bad} injected`, `${args.length} arguments traced`] : third ? ['mid', 'Arguments', `${third} from content`, 'copied from tool output'] : ['ok', 'Arguments', 'Clean', 'from user or system'],
  ].map(([c, t, v, sub]) => `<div class="sig ${c}"><div class="t">${t}</div><div class="v">${esc(v)}</div><div class="s" title="${esc(sub)}">${esc(sub)}</div></div>`).join('');
}

function renderCard(anim) {
  const c = cur(), card = $('card');
  if (!c) { card.className = 'card'; card.innerHTML = '<div class="empty"><h2>Nothing here</h2></div>'; return; }
  const inp = c.input || {}, call = inp.proposed_call || {};
  const trust = Object.fromEntries((inp.provenance || []).filter((p) => p.arg).map((p) => [p.arg, p.trust]));
  const args = Object.entries(call.args || {}).map(([k, v]) => {
    const t = trust[k], txt = typeof v === 'object' ? JSON.stringify(v) : String(v);
    return `<span class="arg ${t === 'untrusted' ? 'bad' : t === 'third_party' ? 'warn' : ''}" title="${esc(k)} = ${esc(txt)}"><i>${esc(k)}</i><b>${esc(txt)}</b></span>`;
  }).join('');
  const thread = (inp.resolution_history || []).map((r) => `<div class="msg"><small>${esc(nice(r.kind))} → ${esc(r.responder)}</small>${esc(r.response)}</div>`).join('');
  card.className = 'card';
  card.innerHTML = '<div class="cin">' +
    `<div class="meta"><span class="tag">${esc(c.suite)}</span><span class="tag">${esc(nice(c.category))}</span>` +
    `<span class="tag ${esc(c.difficulty)}">${esc(c.difficulty)}</span>${c.round ? '<span class="tag">follow-up round</span>' : ''}</div>` +
    `<div class="k">The user asked</div><p class="quote">${esc(inp.user?.prompt || '—')}</p>` +
    `<div class="k">The agent wants to</div><div class="action"><span class="fn">${esc(call.function)}</span>${args}</div>` +
    `<div class="signals">${signals(inp)}</div>` +
    (thread ? `<div class="k">Conversation so far</div><div class="thread">${thread}</div>` : '') + '</div>';
  renderEvidence(inp);
  if (anim) { card.classList.remove('enter'); void card.offsetWidth; card.classList.add('enter'); }
}

/* evidence is always shown on the right */
const compact = (t) => String(t ?? '').split('\n').map((l) => l.trimEnd()).filter((l) => l.trim()).join('\n');
function renderEvidence(inp) {
  const blocks = (inp.untrusted_content || []).map((u) =>
    `<div class="src">${esc(u.id)} · ${esc(u.source)}</div><pre>${esc(compact(u.text))}</pre>`).join('');
  $('evTools').innerHTML = blocks || '<div class="none">none</div>';
  $('fullText').innerHTML = (inp.untrusted_content || []).map((u) =>
    `<div class="src" style="color:var(--warn);font:600 12px var(--mono);margin:10px 0 3px">${esc(u.id)} · ${esc(u.source)}</div><pre>${esc(u.text)}</pre>`).join('');
  $('evPolicy').innerHTML = (inp.policy_clauses || []).map((p) =>
    `<div class="clause"><code>${esc(p.id)}</code><b>${esc(p.title)}</b> — ${esc(p.text)}</div>`).join('') || '<div class="none">none</div>';
}

/* nothing scrolls: shrink text until each box fits its space */
function fitFont(el, max = 12.5, min = 6.5) {
  let s = max;
  el.style.fontSize = `${s}px`;
  while (el.scrollHeight > el.clientHeight + 1 && s > min) { s -= 0.25; el.style.fontSize = `${s}px`; }
}
function fitZoom(box, min = 0.5) {            // scale the card's content (not the card) until it fits the card
  const inner = box.querySelector('.cin');
  if (!inner) return;
  let z = 1;
  inner.style.zoom = 1;
  while (box.scrollHeight > box.clientHeight + 1 && z > min) { z -= 0.03; inner.style.zoom = z; }
}
/* evidence: tool outputs and policy share the column by content; shrink both together; if still too long, flow the
   tool outputs into two columns; as a last resort clip them with an "open full text" link */
function fitEvidence() {
  const t = $('evTools'), p = $('evPolicy');
  t.querySelector('.full')?.remove();
  t.classList.remove('clipped');
  t.style.columnCount = 1;
  const over = () => t.scrollHeight > t.clientHeight + 1 || p.scrollHeight > p.clientHeight + 1;
  const size = (s) => { t.style.fontSize = `${s}px`; p.style.fontSize = `${s + 0.5}px`; };
  let s = 12;
  size(s);
  while (over() && s > 8.5) { s -= 0.25; size(s); }
  if (over()) {
    t.style.columnCount = 2;
    t.style.columnGap = '14px';
    s = 11; size(s);
    while (over() && s > 7.5) { s -= 0.25; size(s); }
  }
  if (t.scrollHeight > t.clientHeight + 1) {
    t.classList.add('clipped');
    const b = document.createElement('button');
    b.className = 'full'; b.textContent = 'open full text';
    b.onclick = () => $('fullDlg').classList.remove('hidden');
    t.appendChild(b);
  }
}
function wrapInner(box) {                       // fitZoom scales an inner wrapper, so the box keeps its size
  if (box.firstElementChild?.classList.contains('cin') && box.children.length === 1) return;
  const w = document.createElement('div');
  w.className = 'cin';
  while (box.firstChild) w.appendChild(box.firstChild);
  box.appendChild(w);
}
function fitAll() {
  fitEvidence();
  fitZoom($('card'), 0.7);
  wrapInner($('panel'));
  fitZoom($('panel'), 0.7);
}

/* ---------- review panel ---------- */
function summary(d) {
  // d: {decision, final_action, missing_evidence, required_authority, clause_ids, user_response}
  const ur = d.user_response;
  return `<span class="dec ${esc(d.decision)}">${esc(nice(d.decision))}</span><span class="arrow">→</span>` +
    `<span class="fin ${esc(d.final_action)}">${esc(d.final_action || '—')}</span>` +
    `<span class="mini">missing <b>${esc(nice(d.missing_evidence))}</b></span>` +
    `<span class="mini">decides <b>${esc(nice(d.required_authority))}</b></span>` +
    ((d.clause_ids || []).length ? `<span class="mini">policy <b>${esc(d.clause_ids.join(', '))}</b></span>` : '') +
    (ur && ur.text ? `</div><div class="replyline">User reply: <b>“${esc(ur.text)}”</b> (${ur.confirmed ? 'confirms' : 'declines'})` : '');
}
function fromVote(v) {
  return { decision: v.gold_decision, final_action: v.gold_final_action, missing_evidence: v.gold_missing_evidence,
    required_authority: v.gold_required_authority, clause_ids: v.gold_clause_ids || [], user_response: v.user_response };
}

function renderPanel() {
  const p = $('panel'), s = sug(), v = mine();
  if (!cur()) { p.innerHTML = ''; return; }
  if (S.mode === 'edit') return renderEdit();
  if (S.mode === 'cant') return renderCant();
  const st = status(v);
  if (st) {
    const label = { accepted: ['acc', '✓ Accepted'], edited: ['edt', '✎ Edited'], cannot_label: ['cant', "⚠ Can't label"] }[st];
    const reason = st === 'cannot_label' ? (REASONS.find((r) => r[0] === v.review.reason) || [, 'Other'])[1] : '';
    p.innerHTML =
      `<div class="ph"><span class="lab">Your review</span><span class="status ${label[0]}">${label[1]}</span></div>` +
      (st === 'cannot_label'
        ? `<div class="why"><small>Why it can't be labelled: ${esc(reason)}</small>${esc(v.review.note)}</div>`
        : `<div class="ph">${summary(fromVote(v))}</div><div class="why"><small>Explanation</small>${esc(v.review.explanation)}</div>`) +
      `<div class="actions"><button class="act edit" id="bEdit">✎ Change <kbd>R</kbd></button>` +
      `<button class="act cant" id="bCant">⚠ Can't label <kbd>C</kbd></button>` +
      `<button class="act ghost" id="bNext">Next unreviewed →</button></div>`;
  } else if (s) {
    p.innerHTML =
      `<div class="ph"><span class="lab">Suggested decision</span>${summary(s)}</div>` +
      `<div class="why"><small>Why</small>${esc(s.explanation)}</div>` +
      `<div class="actions"><button class="act accept" id="bAccept">✓ Accept <kbd>A</kbd></button>` +
      `<button class="act edit" id="bEdit">✎ Reject &amp; edit <kbd>R</kbd></button>` +
      `<button class="act cant" id="bCant">⚠ Can't label <kbd>C</kbd></button></div>`;
  } else {
    p.innerHTML = '<div class="ph"><span class="lab">No suggestion for this case</span></div>' +
      `<div class="actions"><button class="act edit" id="bEdit">✎ Label it <kbd>R</kbd></button>` +
      `<button class="act cant" id="bCant">⚠ Can't label <kbd>C</kbd></button></div>`;
  }
  if ($('bAccept')) $('bAccept').onclick = accept;
  if ($('bEdit')) $('bEdit').onclick = startEdit;
  if ($('bCant')) $('bCant').onclick = startCant;
  if ($('bNext')) $('bNext').onclick = nextUnreviewed;
  fitAll();
}

function chipRow(field, values, selected, suggested) {
  return `<div class="chips" data-f="${field}">${values.map((x) =>
    `<button class="${x === selected ? 'on' : ''}${x === suggested ? ' suggested' : ''} ${field === 'final_action' ? x : ''}" data-v="${x}">${esc(nice(x))}</button>`).join('')}</div>`;
}
function draftReady(d) {
  if (!d.decision || !d.final_action || !d.missing_evidence || !d.required_authority) return 'Pick decision, outcome, missing evidence and who decides';
  if (d.decision === 'ASK_USER' && (!(d.user_response?.text || '').trim() || typeof d.user_response?.confirmed !== 'boolean')) return 'Write the user reply and whether it confirms';
  if (!d.explanation.trim()) return 'Write why this is the right decision';
  return null;
}

function startEdit() {
  const v = mine(), s = sug();
  const base = status(v) && status(v) !== 'cannot_label' ? { ...fromVote(v), explanation: v.review.explanation } :
    s ? { ...s, clause_ids: [...(s.clause_ids || [])], user_response: s.user_response ? { ...s.user_response } : null } :
      { decision: null, final_action: null, missing_evidence: null, required_authority: null, clause_ids: [], user_response: null, explanation: '' };
  S.draft = base;
  S.mode = 'edit';
  renderPanel();
  setTimeout(() => $('expl')?.focus(), 30);
}
function renderEdit() {
  const d = S.draft, s = sug() || {};
  const ur = d.user_response || {};
  const wait = draftReady(d);
  $('panel').innerHTML =
    `<div class="ph"><span class="lab">Correct the decision</span><span class="mini">• = suggested</span></div>` +
    `<div class="grid2">` +
    `<span class="lab">Decision</span><div class="decrow" data-f="decision">${['ALLOW', 'BLOCK', 'ASK_USER', 'ESCALATE'].map((x) =>
      `<button class="${x} ${x === d.decision ? 'on' : ''}" data-v="${x}">${x === s.decision ? '• ' : ''}${nice(x)}</button>`).join('')}</div>` +
    `<span class="lab">Outcome</span>${chipRow('final_action', ['ALLOW', 'BLOCK'], d.final_action, s.final_action)}` +
    `<span class="lab">Missing</span>${chipRow('missing_evidence', S.cfg.vocab.missing_evidence, d.missing_evidence, s.missing_evidence)}` +
    `<span class="lab">Who decides</span>${chipRow('required_authority', S.cfg.vocab.required_authority, d.required_authority, s.required_authority)}` +
    (d.decision === 'ASK_USER'
      ? `<span class="lab">User says</span><input class="reply" id="ureply" placeholder="What does the user answer?" value="${esc(ur.text || '')}">` +
        `<span class="lab">Confirms?</span><div class="chips" data-f="confirmed"><button class="yes ${ur.confirmed === true ? 'on' : ''}" data-v="yes">Yes</button>` +
        `<button class="no ${ur.confirmed === false ? 'on' : ''}" data-v="no">No</button></div>` : '') +
    `<span class="lab">Explanation</span><textarea class="expl" id="expl" placeholder="Why is this the right decision?">${esc(d.explanation)}</textarea>` +
    `</div><div class="foot2"><span class="hintx ${wait ? '' : 'ok'}" id="hint">${wait ? esc(wait) : '✓ Ready'}</span>` +
    `<span class="spacer"></span><button class="act ghost" id="bCancel">Cancel <kbd>Esc</kbd></button>` +
    `<button class="done-btn" id="bSave" ${wait ? 'disabled' : ''}>Save · next ⏎</button></div>`;
  const p = $('panel');
  p.querySelectorAll('.decrow button').forEach((b) => { b.onclick = () => setDraftDecision(b.dataset.v); });
  p.querySelectorAll('.chips[data-f]').forEach((g) => g.querySelectorAll('button').forEach((b) => {
    b.onclick = () => {
      if (g.dataset.f === 'confirmed') S.draft.user_response = { ...(S.draft.user_response || {}), confirmed: b.dataset.v === 'yes' };
      else S.draft[g.dataset.f] = b.dataset.v;
      renderEdit();
    };
  }));
  if ($('ureply')) $('ureply').oninput = (e) => { S.draft.user_response = { ...(S.draft.user_response || {}), text: e.target.value }; refreshHint(); };
  $('expl').oninput = (e) => { S.draft.explanation = e.target.value; refreshHint(); };
  $('bCancel').onclick = cancel;
  $('bSave').onclick = saveEdit;
  fitAll();
}
function setDraftDecision(x) {
  const d = S.draft;
  if (d.decision !== x) {
    const [m, a] = DEF[x];
    Object.assign(d, { decision: x, missing_evidence: m, required_authority: a,
      final_action: x === 'ALLOW' || x === 'BLOCK' ? x : null });
    if (x !== 'ASK_USER') d.user_response = null;
  }
  renderEdit();
}
function refreshHint() {
  const wait = draftReady(S.draft);
  $('hint').className = `hintx ${wait ? '' : 'ok'}`;
  $('hint').textContent = wait || '✓ Ready';
  $('bSave').disabled = !!wait;
}

function startCant() {
  const v = mine();
  S.draft = status(v) === 'cannot_label' ? { reason: v.review.reason, note: v.review.note } : { reason: null, note: '' };
  S.mode = 'cant';
  renderPanel();
}
function renderCant() {
  const d = S.draft;
  const ok = d.reason && d.note.trim();
  $('panel').innerHTML =
    `<div class="ph"><span class="lab">Why can't this case be labelled?</span></div>` +
    `<div class="chips" id="reasons">${REASONS.map(([k, t]) => `<button class="${k === d.reason ? 'on' : ''}" data-v="${k}">${t}</button>`).join('')}</div>` +
    `<textarea class="expl" id="cnote" style="margin-top:10px" placeholder="Explain what is wrong with this case, so the team can fix or drop it">${esc(d.note)}</textarea>` +
    `<div class="foot2"><span class="hintx ${ok ? 'ok' : ''}" id="hint">${ok ? '✓ Ready' : 'Pick a reason and write a short note'}</span>` +
    `<span class="spacer"></span><button class="act ghost" id="bCancel">Cancel <kbd>Esc</kbd></button>` +
    `<button class="done-btn" id="bSave" ${ok ? '' : 'disabled'}>Save · next ⏎</button></div>`;
  $('reasons').querySelectorAll('button').forEach((b) => { b.onclick = () => { S.draft.reason = b.dataset.v; renderCant(); }; });
  $('cnote').oninput = (e) => {
    S.draft.note = e.target.value;
    const r = S.draft.reason && S.draft.note.trim();
    $('hint').className = `hintx ${r ? 'ok' : ''}`; $('hint').textContent = r ? '✓ Ready' : 'Pick a reason and write a short note';
    $('bSave').disabled = !r;
  };
  $('bCancel').onclick = cancel;
  $('bSave').onclick = saveCant;
  fitAll();
  setTimeout(() => $('cnote')?.focus(), 30);
}
function cancel() { S.mode = 'view'; S.draft = null; renderPanel(); }

/* ---------- saving ---------- */
async function save(vote) {
  const c = cur(), prev = S.votes[c.case_id];
  S.votes[c.case_id] = vote;
  try {
    await api('/api/vote', { annotator: S.who, batch_id: S.batch, case_id: c.case_id, vote });
  } catch (e) { if (prev) S.votes[c.case_id] = prev; else delete S.votes[c.case_id]; renderTicks(); toast(`Not saved: ${e.message}`); }
}
function voteFrom(d, statusName) {
  return { gold_decision: d.decision, gold_final_action: d.final_action, gold_missing_evidence: d.missing_evidence,
    gold_required_authority: d.required_authority, gold_clause_ids: d.clause_ids || [], user_response: d.user_response || null,
    notes: d.explanation, review: { status: statusName, explanation: d.explanation, suggested: sug() } };
}
function accept() {
  const s = sug();
  if (!s || S.busy) return;
  save(voteFrom(s, 'accepted'));
  advance('ALLOW');
}
function saveEdit() {
  if (draftReady(S.draft)) return;
  const s = sug() || {};
  const same = ['decision', 'final_action', 'missing_evidence', 'required_authority'].every((f) => S.draft[f] === s[f]) &&
    S.draft.explanation.trim() === (s.explanation || '').trim();
  save(voteFrom(S.draft, same ? 'accepted' : 'edited'));
  advance(S.draft.decision === 'BLOCK' ? 'BLOCK' : 'ASK_USER');
}
function saveCant() {
  const d = S.draft;
  if (!d.reason || !d.note.trim()) return;
  save({ gold_decision: null, gold_final_action: null, gold_missing_evidence: null, gold_required_authority: null,
    gold_clause_ids: [], user_response: null, notes: d.note,
    review: { status: 'cannot_label', reason: d.reason, note: d.note, suggested: sug() } });
  advance('ESCALATE');
}

/* ---------- navigation ---------- */
function advance(flyClass) {
  S.busy = true;
  S.mode = 'view'; S.draft = null;
  $('card').classList.add(`fly-${flyClass}`);
  setTimeout(() => { S.busy = false; nextUnreviewed(true); }, 360);
}
function nextUnreviewed(fromSave) {
  const n = S.cases.length;
  for (let k = 1; k <= n; k++) {
    const j = (S.i + k) % n;
    if (!status(S.votes[S.cases[j].case_id])) return go(j, true);
  }
  toast('Every case in this batch is reviewed');
  if (fromSave) go(S.i, true);
}
function go(i, anim) {
  if (!S.cases.length) return;
  S.i = (i + S.cases.length) % S.cases.length;
  S.mode = 'view'; S.draft = null;
  put(KEY.pos(S.who), { batch: S.batch, i: S.i });
  render(anim);
}
function render(anim) {
  renderCard(anim);
  renderPanel();
  renderTicks();
  $('pos').textContent = `${S.i + 1} / ${S.cases.length}`;
}
function renderTicks() {
  const cnt = { accepted: 0, edited: 0, cannot_label: 0 };
  $('ticks').innerHTML = S.cases.map((c, i) => {
    const st = status(S.votes[c.case_id]);
    if (st) cnt[st] += 1;
    const cls = { accepted: 'acc', edited: 'edt', cannot_label: 'cant' }[st] || '';
    return `<button class="${cls}${i === S.i ? ' cur' : ''}" data-i="${i}" title="Case ${i + 1}${st ? ' · ' + nice(st) : ''}"></button>`;
  }).join('');
  $('ticks').querySelectorAll('button').forEach((b) => { b.onclick = () => go(+b.dataset.i, true); });
  const sw = (c, t, n) => `<span><i style="background:${c}"></i>${t} ${n}</span>`;
  $('counts').innerHTML = sw('var(--allow)', 'accepted', cnt.accepted) + sw('#a78bfa', 'edited', cnt.edited) +
    sw('var(--warn)', "can't label", cnt.cannot_label);
}

/* ---------- wiring ---------- */
window.addEventListener('resize', fitAll);
$('closeFull').onclick = () => $('fullDlg').classList.add('hidden');
$('fullDlg').onclick = (e) => { if (e.target.id === 'fullDlg') $('fullDlg').classList.add('hidden'); };
document.fonts?.ready.then(fitAll);
$('prev').onclick = () => go(S.i - 1, true);
$('next').onclick = () => go(S.i + 1, true);
$('batch').onchange = (e) => loadBatch(e.target.value, 0);
$('me').onclick = async () => { if (confirm('Switch reviewer?')) await setWho(await pickWho()); };
document.addEventListener('keydown', (e) => {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);
  if (e.key === 'Escape') {
    if (!$('fullDlg').classList.contains('hidden')) $('fullDlg').classList.add('hidden');
    else if (S.mode !== 'view') cancel(); else if (typing) e.target.blur();
    return;
  }
  if (e.key === 'Enter' && !e.shiftKey && S.mode !== 'view' && !$('bSave')?.disabled) {
    if (e.target.tagName === 'TEXTAREA' && !e.ctrlKey) return;      // plain Enter adds a line; Ctrl+Enter saves
    e.preventDefault(); $('bSave').click(); return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (S.mode === 'edit' && ['1', '2', '3', '4'].includes(k)) { setDraftDecision(['ALLOW', 'BLOCK', 'ASK_USER', 'ESCALATE'][+k - 1]); }
  else if (k === 'a' && S.mode === 'view' && !status(mine())) accept();
  else if (k === 'r') startEdit();
  else if (k === 'c') startCant();
  else if (e.key === 'ArrowRight') go(S.i + 1, true);
  else if (e.key === 'ArrowLeft') go(S.i - 1, true);
  else return;
  e.preventDefault();
});

(async () => {
  S.cfg = await api('/api/config');
  const saved = get(KEY.who, null) || new URLSearchParams(location.search).get('annotator');
  await setWho(S.cfg.annotators.includes(saved) ? saved : await pickWho());
})();
