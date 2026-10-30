/* Labelling tool ("focus" design). Every change is saved at once: first to this browser (a localStorage queue),
   then to the local server, which writes your own vote file. Unsent changes are re-sent on the next load. */

const $ = (id) => document.getElementById(id);
const S = {
  who: null, cfg: null, batches: [], batch: null, role: null, cases: [], votes: {}, others: {}, policies: [],
  i: 0, evidence: false, busy: false, sending: false,
};
const KEY = { who: 'labeler.who', pos: (w) => `labeler.focus.${w}`, queue: (w) => `labeler.queue.${w}` };
const DEF = { ALLOW: ['none', 'current_user'], BLOCK: ['none', 'none'], ASK_USER: ['user_intent', 'current_user'], ESCALATE: ['approval', 'manager'] };
const COLOR = { ALLOW: 'var(--allow)', BLOCK: 'var(--block)', ASK_USER: 'var(--ask)', ESCALATE: 'var(--esc)' };

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nice = (s) => String(s ?? '').replace(/_/g, ' ');
const get = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const put = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };
async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}
function toast(t) { const el = document.createElement('div'); el.className = 'toast'; el.textContent = t; document.body.appendChild(el); setTimeout(() => el.remove(), 2400); }
const complete = (v) => !!v && !!v.gold_decision && !!v.gold_final_action && !!v.gold_missing_evidence && !!v.gold_required_authority &&
  (v.gold_decision !== 'ASK_USER' || (!!(v.user_response?.text || '').trim() && typeof v.user_response?.confirmed === 'boolean'));
const cur = () => S.cases[S.i];
const vote = () => S.votes[cur()?.case_id] || {};

/* ---------- people & batches ---------- */
function pickWho() {
  return new Promise((res) => {
    $('people').innerHTML = S.cfg.annotators.map((n) => `<button data-n="${n}">${n}</button>`).join('');
    $('people').querySelectorAll('button').forEach((b) => { b.onclick = () => { $('whoDlg').classList.add('hidden'); res(b.dataset.n); }; });
    $('whoDlg').classList.remove('hidden');
  });
}
async function setWho(n) {
  S.who = n;
  put(KEY.who, n);
  $('who').textContent = n;
  $('avatar').textContent = n[0].toUpperCase();
  await flush();
  S.batches = await api(`/api/batches?annotator=${n}`);
  const label = (b) => `${b.batch_id.replace('batch_', 'Batch ')}${b.role === 'tiebreak' ? ' · tie-break' : ''} · ${b.done}/${b.total}`;
  $('batch').innerHTML = S.batches.filter((b) => b.role).map((b) => `<option value="${b.batch_id}">${label(b)}</option>`).join('');
  const pos = get(KEY.pos(n), {});
  const first = S.batches.find((b) => b.role && b.batch_id === pos.batch) || S.batches.find((b) => b.role);
  if (first) await loadBatch(first.batch_id, pos.batch === first.batch_id ? pos.i : 0);
}
async function loadBatch(id, i = 0) {
  const d = await api(`/api/batch?id=${id}&annotator=${S.who}`);
  Object.assign(S, { batch: id, role: d.role, cases: d.cases, votes: d.votes, others: d.others || {} });
  for (const q of get(KEY.queue(S.who), [])) {            // unsent local changes win over the server copy
    if (q.batch_id === id) { if (q.vote) S.votes[q.case_id] = q.vote; else delete S.votes[q.case_id]; }
  }
  $('batch').value = id;
  $('role').textContent = d.role === 'tiebreak' ? 'tie-break' : 'primary · blind';
  go(Math.min(i, Math.max(S.cases.length - 1, 0)), true);
}

/* ---------- rendering ---------- */
function signals(inp) {
  const prov = inp.provenance || [];
  const origin = prov.find((p) => p.kind === 'call') || {};
  const args = prov.filter((p) => p.kind === 'arg');
  const bad = args.filter((p) => p.trust === 'untrusted').length;
  const third = args.filter((p) => p.trust === 'third_party').length;
  const a = inp.authority || {};
  const s = inp.sensitivity || {};
  const role = a.required_role || a.required_authority;
  const out = [
    origin.trust === 'untrusted'
      ? ['bad', 'Origin', 'Injected', `from ${origin.instruction_origin || 'content'}${origin.origin_source ? ` (${origin.origin_source})` : ''}`]
      : ['ok', 'Origin', 'The user', 'request came from the user'],
    a.user_may_authorize === false
      ? ['mid', 'Authority', nice(role || 'higher role'), (a.basis || []).map(nice).join(', ') || 'user cannot authorize']
      : ['ok', 'Authority', 'User may act', nice(role || 'current user')],
    s.flow === 'high_to_low'
      ? ['bad', 'Data flow', 'High → low', `${s.resource} → ${s.destination}`]
      : ['info', 'Data flow', s.resource || '—', s.destination ? `to ${s.destination}` : 'no outgoing data'],
    bad ? ['bad', 'Arguments', `${bad} injected`, `${args.length} arguments traced`]
      : third ? ['mid', 'Arguments', `${third} from content`, 'copied from tool output'] : ['ok', 'Arguments', 'Clean', 'from user or system'],
  ];
  return out.map(([c, t, v, sub]) => `<div class="sig ${c}"><div class="t">${t}</div><div class="v">${esc(v)}</div>` +
    `<div class="s" title="${esc(sub)}">${esc(sub)}</div></div>`).join('');
}

function clauseHtml(p, terms) {
  const cited = (vote().gold_clause_ids || []).includes(p.id);
  const hl = (t) => (terms ? highlight(t, terms) : esc(t));
  return `<div class="clause"><div class="ct"><code>${esc(p.id)}</code><b>${hl(p.title)}</b> — ${hl(p.text)}</div>` +
    `<button class="cite${cited ? ' on' : ''}" data-id="${esc(p.id)}">${cited ? 'cited' : 'cite'}</button></div>`;
}
function bindCites(root) {
  root.querySelectorAll('.cite').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); toggleCite(b.dataset.id); }; });
}

function otherVotes(c) {
  const list = S.role === 'tiebreak' ? S.others[c.case_id] || [] : [];
  if (!list.length) return '';
  return `<div class="k">Primary votes — they disagree</div><div class="others">${list.map((v) =>
    `<div class="ov"><div class="who"><span>${esc(v.annotator[0].toUpperCase())}</span>${esc(v.annotator)}</div>` +
    `<span class="d" style="color:${COLOR[v.gold_decision] || '#fff'}">${esc(nice(v.gold_decision))}</span> → <b>${esc(v.gold_final_action)}</b>` +
    ` · ${esc(nice(v.gold_missing_evidence))} · ${esc(nice(v.gold_required_authority))}` +
    (v.user_response?.text ? `<div>“${esc(v.user_response.text)}” (${v.user_response.confirmed ? 'yes' : 'no'})</div>` : '') +
    (v.notes ? `<div><i>${esc(v.notes)}</i></div>` : '') + '</div>').join('')}</div>`;
}

function render(anim) {
  const c = cur();
  const card = $('card');
  renderTicks();
  if (!c) {
    card.className = 'card';
    card.innerHTML = `<div class="empty"><h2>${S.role === 'tiebreak' ? 'No disputes yet' : 'Nothing here'}</h2>` +
      `<p>${S.role === 'tiebreak' ? 'Disputed cases appear once both primary annotators have voted and pushed — then pull.' : 'This batch has no cases.'}</p></div>`;
    $('pos').textContent = '0 / 0';
    $('done').textContent = '';
    $('sheet').classList.add('hidden');
    return;
  }
  const inp = c.input || {};
  const call = inp.proposed_call || {};
  const v = vote();
  const trust = Object.fromEntries((inp.provenance || []).filter((p) => p.arg).map((p) => [p.arg, p.trust]));
  const args = Object.entries(call.args || {}).map(([k, val]) => {
    const t = trust[k];
    const txt = typeof val === 'object' ? JSON.stringify(val) : String(val);
    return `<span class="arg ${t === 'untrusted' ? 'bad' : t === 'third_party' ? 'warn' : ''}" title="${esc(k)} = ${esc(txt)} (${esc(t || 'unknown')})">` +
      `<i>${esc(k)}</i><b>${esc(txt)}</b></span>`;
  }).join('');
  const thread = (inp.resolution_history || []).map((r) =>
    `<div class="msg"><small>${esc(nice(r.kind))} → ${esc(r.responder)}</small>${esc(r.response)}</div>`).join('');
  const untrusted = (inp.untrusted_content || []).map((u) => `<div class="src">${esc(u.id)} · ${esc(u.source)}</div><pre>${esc(u.text)}</pre>`).join('') || '<pre>none</pre>';
  const pol = (inp.policy_clauses || []).map((p) => clauseHtml(p)).join('') || '<div class="clause">none</div>';
  const cited = (v.gold_clause_ids || []).map((id) => `<span class="tagc">${esc(id)}<button data-id="${esc(id)}" title="remove">×</button></span>`).join('');

  card.className = `card${v.gold_decision ? ` glow-${v.gold_decision}` : ''}`;
  card.innerHTML =
    `<div class="meta"><span class="tag">${esc(c.suite)}</span><span class="tag">${esc(nice(c.category))}</span>` +
    `<span class="tag ${esc(c.difficulty)}">${esc(c.difficulty)}</span>${c.round ? '<span class="tag">follow-up round</span>' : ''}` +
    `${complete(v) ? '<span class="done">✓ labelled</span>' : ''}` +
    `${v.gold_decision ? `<button class="link" id="clear" title="Delete your vote on this case">clear</button>` : ''}</div>` +
    otherVotes(c) +
    `<div class="k">The user asked</div><p class="quote">${esc(inp.user?.prompt || '—')}</p>` +
    `<div class="k">The agent wants to</div><div class="action"><span class="fn">${esc(call.function)}</span>${args}</div>` +
    `<div class="signals">${signals(inp)}</div>` +
    (thread ? `<div class="k">Conversation so far</div><div class="thread">${thread}</div>` : '') +
    `<button class="more" id="more">${S.evidence ? 'Hide evidence ▲' : 'Show evidence — tool outputs & policy ▼'}</button>` +
    (S.evidence ? `<div class="evidence"><div class="box"><div class="k">Tool outputs (untrusted)</div>${untrusted}</div>` +
      `<div class="box"><div class="k">Retrieved policy</div>${pol}</div></div>` : '') +
    `<div class="foot">${cited}<input class="note" id="note" placeholder="Note (optional)" value="${esc(v.notes || '')}"></div>`;

  $('more').onclick = () => { S.evidence = !S.evidence; render(); };
  if ($('clear')) $('clear').onclick = clearVote;
  $('note').oninput = (e) => edit({ notes: e.target.value }, false);
  card.querySelectorAll('.tagc button').forEach((b) => { b.onclick = () => toggleCite(b.dataset.id); });
  bindCites(card);
  if (anim) { card.classList.remove('enter'); void card.offsetWidth; card.classList.add('enter'); }

  $('pos').textContent = `${S.i + 1} / ${S.cases.length}`;
  const n = S.cases.filter((x) => complete(S.votes[x.case_id])).length;
  $('done').textContent = `· ${n} labelled`;
  document.querySelectorAll('#dock button').forEach((b) => b.classList.toggle('on', b.dataset.d === v.gold_decision));
  renderSheet();
}

function renderTicks() {
  $('ticks').innerHTML = S.cases.map((c, i) => {
    const v = S.votes[c.case_id];
    const cls = complete(v) ? v.gold_decision : v?.gold_decision ? 'part' : '';
    return `<button class="${cls}${i === S.i ? ' cur' : ''}" data-i="${i}" title="Case ${i + 1}${v?.gold_decision ? ` · ${nice(v.gold_decision)}` : ''}"></button>`;
  }).join('');
  $('ticks').querySelectorAll('button').forEach((b) => { b.onclick = () => go(+b.dataset.i, true); });
}

function chips(field, values, selected, cls = () => '') {
  return `<div class="chips" data-f="${field}">${values.map((x) =>
    `<button class="${cls(x)}${x === selected ? ' on' : ''}" data-v="${x}">${esc(nice(x))}</button>`).join('')}</div>`;
}
function yesNo(field, value, withNone) {
  const b = (v, label, cls, on) => `<button class="${cls}${on ? ' on' : ''}" data-v="${v}">${label}</button>`;
  return `<div class="chips" data-f="${field}">${b('yes', 'Yes', 'yes', value === true)}${b('no', 'No', 'no', value === false)}` +
    `${withNone ? b('none', 'Unclear', 'none-v', value === null) : ''}</div>`;
}

function renderSheet() {
  const v = vote();
  const d = v.gold_decision;
  const sh = $('sheet');
  if (d !== 'ASK_USER' && d !== 'ESCALATE') { sh.classList.add('hidden'); return; }
  const u = v.user_response || {};
  const noisy = u.noisy_text !== undefined && u.noisy_text !== null;
  const ok = complete(v);
  sh.innerHTML =
    `<span class="lab">${d === 'ASK_USER' ? 'Then' : 'If approved'}</span>` +
    chips('gold_final_action', ['ALLOW', 'BLOCK'], v.gold_final_action, (x) => x) +
    `<span class="lab">Missing</span>${chips('gold_missing_evidence', S.cfg.vocab.missing_evidence, v.gold_missing_evidence)}` +
    `<span class="lab">Who decides</span>${chips('gold_required_authority', S.cfg.vocab.required_authority, v.gold_required_authority)}` +
    (d === 'ASK_USER'
      ? `<span class="lab">User says</span><div class="line"><input class="reply" id="reply" placeholder="Type the user's answer…" value="${esc(u.text || '')}">` +
        `${yesNo('confirmed', u.confirmed)}<label class="toggle"><input type="checkbox" id="noisyOn" ${noisy ? 'checked' : ''}><span></span>noisy</label></div>` +
        (noisy ? `<span class="lab">Noisy reply</span><div class="line"><input class="reply" id="noisyText" placeholder="Wrong or unhelpful answer" value="${esc(u.noisy_text || '')}">` +
          `${yesNo('noisy_confirmed', u.noisy_confirmed, true)}</div>` : '')
      : '') +
    `<div class="go"><span class="state${ok ? ' okay' : ''}" id="sheetState">${ok ? '✓ Ready' : d === 'ASK_USER'
      ? 'Pick the outcome, write the reply and whether it confirms' : 'Pick the outcome if approved'}</span>` +
    `<button class="done-btn" id="doneBtn" ${ok ? '' : 'disabled'}>Done · next ⏎</button></div>`;
  sh.classList.remove('hidden');
  sh.querySelectorAll('.chips[data-f]').forEach((g) => g.querySelectorAll('button').forEach((b) => {
    b.onclick = () => {
      const f = g.dataset.f;
      if (f === 'confirmed') editReply({ confirmed: b.dataset.v === 'yes' });
      else if (f === 'noisy_confirmed') editReply({ noisy_confirmed: b.dataset.v === 'none' ? null : b.dataset.v === 'yes' });
      else edit({ [f]: b.dataset.v });
    };
  }));
  if ($('reply')) $('reply').oninput = (e) => editReply({ text: e.target.value }, false);
  if ($('noisyText')) $('noisyText').oninput = (e) => editReply({ noisy_text: e.target.value }, false);
  if ($('noisyOn')) {
    $('noisyOn').onchange = (e) => editReply(e.target.checked ? { noisy_text: '', noisy_confirmed: null } : { noisy_text: null, noisy_confirmed: null });
  }
  $('doneBtn').onclick = () => advance(d);
}

/* while typing, update only the readiness indicators (re-rendering would steal the focus) */
function refreshLight() {
  const ok = complete(vote());
  if ($('sheetState') && ok) { $('sheetState').className = 'state okay'; $('sheetState').textContent = '✓ Ready'; }
  if ($('doneBtn')) $('doneBtn').disabled = !ok;
  renderTicks();
  $('done').textContent = `· ${S.cases.filter((x) => complete(S.votes[x.case_id])).length} labelled`;
}

/* ---------- editing ---------- */
function edit(patch, rerender = true) {
  const c = cur();
  if (!c) return;
  const v = { ...vote(), ...patch };
  S.votes[c.case_id] = v;
  enqueue(c.case_id, v);
  if (rerender) render(); else refreshLight();
}
function editReply(patch, rerender = true) { edit({ user_response: { ...(vote().user_response || {}), ...patch } }, rerender); }

function decide(d) {
  if (!cur() || S.busy) return;
  const [m, a] = DEF[d];
  const old = vote();
  const v = { ...old, gold_decision: d, gold_missing_evidence: m, gold_required_authority: a,   // keeps cited clauses + note
    gold_final_action: d === 'ALLOW' || d === 'BLOCK' ? d : (old.gold_decision === d ? old.gold_final_action : null) };
  if (d !== 'ASK_USER') v.user_response = null;
  edit(v);
  if (d === 'ALLOW' || d === 'BLOCK') advance(d);
  else setTimeout(() => (d === 'ASK_USER' ? $('reply') : null)?.focus(), 60);
}

function toggleCite(id) {
  const ids = new Set(vote().gold_clause_ids || []);
  if (ids.has(id)) ids.delete(id); else ids.add(id);
  edit({ gold_clause_ids: [...ids].sort() });
  if (!$('drawer').classList.contains('hidden')) search();
}

function clearVote() {
  const c = cur();
  if (!c || !S.votes[c.case_id] || !confirm('Delete your vote on this case?')) return;
  delete S.votes[c.case_id];
  enqueue(c.case_id, null);
  render();
}

function advance(d) {
  S.busy = true;
  $('card').classList.add(`fly-${d}`);
  setTimeout(() => {
    S.busy = false;
    const next = S.cases.findIndex((c, j) => j > S.i && !complete(S.votes[c.case_id]));
    if (next === -1 && S.cases.every((c) => complete(S.votes[c.case_id]))) {
      toast('Batch complete — commit and push your votes');
      go(S.i, true);
    } else go(next === -1 ? S.i + 1 : next, true);
  }, 380);
}
function go(i, anim) {
  if (!S.cases.length) { S.i = 0; render(); return; }
  S.i = (i + S.cases.length) % S.cases.length;
  put(KEY.pos(S.who), { batch: S.batch, i: S.i });
  render(anim);
}
function nextUnlabelled() {
  for (let k = 1; k <= S.cases.length; k++) {
    const j = (S.i + k) % S.cases.length;
    if (!complete(S.votes[S.cases[j].case_id])) return go(j, true);
  }
  toast('Every case in this batch is labelled');
}

/* ---------- saving: browser queue first, then the server ---------- */
function enqueue(caseId, v) {
  const q = get(KEY.queue(S.who), []).filter((x) => !(x.batch_id === S.batch && x.case_id === caseId));
  q.push({ batch_id: S.batch, case_id: caseId, vote: v });
  put(KEY.queue(S.who), q);
  setSave('saving…', 'busy');
  clearTimeout(enqueue.t);
  enqueue.t = setTimeout(flush, 300);
}
async function flush() {
  if (!S.who || S.sending) return;
  S.sending = true;
  let failed = false;
  try {
    let q = get(KEY.queue(S.who), []);
    while (q.length) {
      const item = q[0];
      try {
        await api('/api/vote', { annotator: S.who, ...item });
      } catch (e) {
        if (e instanceof TypeError) { setSave('offline — kept in this browser', 'err'); setTimeout(flush, 5000); return; }
        failed = true;                                     // rejected by the server: report it, drop it, keep going
        setSave('not saved', 'err');
        toast(`Not saved: ${e.message}`);
      }
      q = get(KEY.queue(S.who), []);
      const k = q.findIndex((x) => x.batch_id === item.batch_id && x.case_id === item.case_id && JSON.stringify(x.vote) === JSON.stringify(item.vote));
      if (k >= 0) q.splice(k, 1);
      put(KEY.queue(S.who), q);
    }
    if (!failed) setSave(`saved ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`, 'ok');
  } finally {
    S.sending = false;
  }
}
function setSave(text, cls) {
  $('save').className = `save ${cls}`;
  $('save').querySelector('span').textContent = text;
}

/* ---------- policy documents ---------- */
function highlight(text, terms) {
  let out = esc(text);
  for (const t of terms) out = out.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>');
  return out;
}
function search() {
  const terms = $('q').value.toLowerCase().split(/\s+/).filter((t) => t.length > 1);
  let html;
  if (!terms.length) {                                    // no query: browse every clause, grouped by document
    html = [...new Set(S.policies.map((p) => p.doc))].map((d) => `<div class="doc">${esc(d)}</div>` +
      S.policies.filter((p) => p.doc === d).map((p) => clauseHtml(p)).join('')).join('');
  } else {
    html = S.policies.map((p) => {
      const hay = `${p.id} ${p.title} ${p.title} ${p.text}`.toLowerCase();
      return { p, s: terms.reduce((n, t) => n + (hay.split(t).length - 1), 0), all: terms.every((t) => hay.includes(t)) };
    }).filter((x) => x.s > 0).sort((a, b) => (b.all - a.all) || (b.s - a.s)).slice(0, 40)
      .map((x) => clauseHtml(x.p, terms)).join('');
  }
  $('results').innerHTML = html || '<div class="clause">no match</div>';
  bindCites($('results'));
}
function drawer(open) {
  $('drawer').classList.toggle('hidden', !open);
  if (open) { search(); $('q').focus(); }
}

/* ---------- wiring ---------- */
$('prev').onclick = () => go(S.i - 1, true);
$('next').onclick = () => go(S.i + 1, true);
$('batch').onchange = (e) => loadBatch(e.target.value, 0);
$('me').onclick = async () => {
  if (!confirm('Switch annotator? Votes stay saved under each name.')) return;
  await setWho(await pickWho());
};
$('btnPolicy').onclick = () => drawer(true);
$('closeDrawer').onclick = () => drawer(false);
$('drawer').onclick = (e) => { if (e.target.id === 'drawer') drawer(false); };
$('q').oninput = search;
document.querySelectorAll('#dock button').forEach((b) => { b.onclick = () => decide(b.dataset.d); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { drawer(false); if (e.target.tagName === 'INPUT') e.target.blur(); return; }
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
    if (e.key === 'Enter' && e.target.id !== 'q' && complete(vote())) advance(vote().gold_decision);
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const d = { 1: 'ALLOW', 2: 'BLOCK', 3: 'ASK_USER', 4: 'ESCALATE' }[e.key];
  if (d) decide(d);
  else if (e.key === 'ArrowRight') go(S.i + 1, true);
  else if (e.key === 'ArrowLeft') go(S.i - 1, true);
  else if (e.key === 'u' || e.key === 'U') nextUnlabelled();
  else if (e.key === 'e' || e.key === 'E') { S.evidence = !S.evidence; render(); }
  else if (e.key === '/') drawer(true);
  else if (e.key === 'Enter' && complete(vote())) advance(vote().gold_decision);
  else return;
  e.preventDefault();
});
window.addEventListener('online', flush);

(async () => {
  S.cfg = await api('/api/config');
  S.policies = await api('/api/policies');
  $('polCount').textContent = `${S.policies.length} clauses`;
  // a saved name wins; ?annotator=<name> only preselects it on a first visit
  const saved = get(KEY.who, null) || new URLSearchParams(location.search).get('annotator');
  await setWho(S.cfg.annotators.includes(saved) ? saved : await pickWho());
})();
