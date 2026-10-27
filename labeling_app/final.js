/**
 * SaGate Final Annotation Interface
 * Mirrors compact.js API usage; works with the same server.py backend.
 */

const S = {
  annotator: 'rinkesh',
  batchId: 'batch_01',
  manifest: null,
  cases: [],
  idx: 0,
  annotations: {},
  cited: new Set(),
  dirty: false,
};

// ── DOM References ──────────────────────────────────
const $ = (id) => document.getElementById(id);

const el = {
  batchSelect:     $('batchSelect'),
  annotatorSelect: $('annotatorSelect'),
  progressBar:     $('progressBar'),
  progressLabel:   $('progressLabel'),
  caseNum:         $('caseNum'),
  caseTotal:       $('caseTotal'),
  saveStatus:      $('saveStatus'),
  btnPrev:         $('btnPrev'),
  btnNext:         $('btnNext'),
  btnUnlabeled:    $('btnUnlabeled'),
  btnExport:       $('btnExport'),
  badgeSuite:      $('badgeSuite'),
  badgeCategory:   $('badgeCategory'),
  badgeDifficulty: $('badgeDifficulty'),
  badgeStatus:     $('badgeStatus'),
  principalText:   $('principalText'),
  promptText:      $('promptText'),
  fnName:          $('fnName'),
  stateBadge:      $('stateBadge'),
  argsBody:        $('argsBody'),
  authText:        $('authText'),
  flowText:        $('flowText'),
  approverText:    $('approverText'),
  untrustedWrap:   $('untrustedWrap'),
  untrustedText:   $('untrustedText'),
  policiesList:    $('policiesList'),
  askExtras:       $('askExtras'),
  escalateExtras:  $('escalateExtras'),
  missingPills:    document.querySelectorAll('#missingPills .pill'),
  authPills:       document.querySelectorAll('#authPills .pill'),
  userReplyInput:  $('userReplyInput'),
  citedTags:       $('citedTags'),
  notesArea:       $('notesArea'),
  btnSaveNext:     $('btnSaveNext'),
};

// ── Init ────────────────────────────────────────────
async function init() {
  const saved = localStorage.getItem('sagate_annotator');
  if (saved) {
    S.annotator = saved;
    el.annotatorSelect.value = saved;
  }
  bindEvents();
  await loadManifest();
  await loadBatch(S.batchId);
}

// ── Manifest & Batch Loading ─────────────────────────
async function loadManifest() {
  try {
    const res = await fetch(`/api/manifest?annotator=${encodeURIComponent(S.annotator)}`);
    S.manifest = await res.json();
    el.batchSelect.innerHTML = '';
    (S.manifest.batches || []).forEach((b) => {
      const opt = document.createElement('option');
      opt.value = b.batch_id;
      opt.textContent = `Batch ${String(b.batch_num).padStart(2,'0')} (${b.labeled_count||0}/${b.case_count})`;
      el.batchSelect.appendChild(opt);
    });
    el.batchSelect.value = S.batchId;
  } catch(e) { console.error('Manifest load failed:', e); }
}

async function loadBatch(batchId) {
  S.batchId = batchId;
  setStatus('Loading…', '');
  try {
    const res = await fetch(`/api/batch?id=${batchId}&annotator=${encodeURIComponent(S.annotator)}`);
    const data = await res.json();
    S.cases = data.cases || [];
    S.annotations = data.annotations || {};
  } catch(e) { console.error('Batch load failed:', e); return; }
  S.idx = 0;
  el.caseTotal.textContent = S.cases.length;
  updateProgress();
  renderCase();
  setStatus('Ready', '');
}

// ── Case Rendering ───────────────────────────────────
function renderCase() {
  if (!S.cases.length) return;
  const item = S.cases[S.idx];
  const raw  = item.raw_case || {};
  const inp  = raw.input || {};

  el.caseNum.textContent = S.idx + 1;

  // Meta strip
  el.badgeSuite.textContent     = item.suite     || 'banking';
  el.badgeCategory.textContent  = item.category  || 'general';
  el.badgeDifficulty.textContent= item.difficulty || 'medium';
  el.principalText.textContent  = inp.user?.principal_id || 'user';

  // Col 1 — Context
  el.promptText.textContent = inp.user?.prompt || '(No prompt provided)';

  const call = inp.proposed_call || {};
  el.fnName.textContent = `${call.function || 'unknown_tool'}()`;
  el.stateBadge.style.display = call.state_changing ? 'inline-block' : 'none';
  renderArgs(call.args || {}, inp.provenance || []);

  // Col 2 — Evidence
  const auth = inp.authority   || {};
  const sens = inp.sensitivity || {};
  el.authText.textContent     = `${auth.principal||'user'} (${auth.principal_role||'role'})`;
  el.flowText.textContent     = `${sens.resource||'PUBLIC'} → ${sens.destination||'INTERNAL'}`;
  el.approverText.textContent = auth.approver || 'None';

  const untrusted = inp.untrusted_content || [];
  if (untrusted.length) {
    el.untrustedWrap.style.display = 'block';
    el.untrustedText.textContent   = untrusted.map(u => `[${u.id} - ${u.source}]\n${u.text}`).join('\n\n');
  } else {
    el.untrustedWrap.style.display = 'none';
  }

  renderPolicies(inp.policy_clauses || []);

  // Col 3 — Decision (restore saved)
  populateDecision();
}

function renderArgs(args, provenance) {
  el.argsBody.innerHTML = '';
  const provMap = {};
  provenance.forEach(p => { if (p.arg) provMap[p.arg] = p; });

  const entries = Object.entries(args);
  if (!entries.length) {
    el.argsBody.innerHTML = '<tr><td colspan="3" style="color:#4a5580;font-size:11px;">No arguments</td></tr>';
    return;
  }
  entries.forEach(([key, val]) => {
    const p = provMap[key];
    const trust = p?.trust || 'unknown';
    const trustClass = trust === 'trusted' ? 'trust-trusted' : trust === 'untrusted' ? 'trust-untrusted' : 'trust-unknown';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${esc(key)}</td>
      <td>${esc(typeof val === 'object' ? JSON.stringify(val) : String(val))}</td>
      <td><span class="trust-badge ${trustClass}">${trust}</span></td>
    `;
    el.argsBody.appendChild(tr);
  });
}

function renderPolicies(clauses) {
  el.policiesList.innerHTML = '';
  if (!clauses.length) {
    el.policiesList.innerHTML = '<div class="empty-state">No policies retrieved for this case.</div>';
    return;
  }
  clauses.forEach(c => {
    const isCited = S.cited.has(c.id);
    const div = document.createElement('div');
    div.className = `policy-item${isCited ? ' cited' : ''}`;
    div.dataset.id = c.id;
    div.innerHTML = `
      <div class="pol-head">
        <span class="pol-id">${esc(c.id)}</span>
        <span class="pol-title">${esc(c.title)}</span>
        <button type="button" class="pol-cite-btn">${isCited ? '✓ Cited' : '+ Cite'}</button>
      </div>
      <div class="pol-text">${esc(c.text)}</div>
    `;
    div.querySelector('.pol-cite-btn').addEventListener('click', e => {
      e.stopPropagation();
      toggleCite(c.id);
    });
    el.policiesList.appendChild(div);
  });
}

function toggleCite(id) {
  if (S.cited.has(id)) S.cited.delete(id);
  else S.cited.add(id);
  renderCitedTags();
  document.querySelectorAll(`.policy-item[data-id="${id}"]`).forEach(el => {
    const cited = S.cited.has(id);
    el.classList.toggle('cited', cited);
    el.querySelector('.pol-cite-btn').textContent = cited ? '✓ Cited' : '+ Cite';
  });
  S.dirty = true;
}

function renderCitedTags() {
  el.citedTags.innerHTML = '';
  if (!S.cited.size) {
    el.citedTags.innerHTML = '<span class="cited-empty">None cited</span>';
    return;
  }
  S.cited.forEach(id => {
    const pill = document.createElement('span');
    pill.className = 'cited-pill';
    pill.innerHTML = `${esc(id)} <span class="remove-x" data-id="${esc(id)}">&times;</span>`;
    pill.querySelector('.remove-x').addEventListener('click', () => toggleCite(id));
    el.citedTags.appendChild(pill);
  });
}

// ── Decision Controls ────────────────────────────────
function setDecision(decision, dirty = true) {
  document.querySelectorAll('.dec-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.decision === decision);
  });
  el.askExtras.style.display      = decision === 'ASK_USER'  ? 'flex' : 'none';
  el.escalateExtras.style.display = decision === 'ESCALATE'  ? 'flex' : 'none';

  // Update status badge
  el.badgeStatus.className = 'badge badge-status';
  if (decision) {
    el.badgeStatus.textContent = decision;
    el.badgeStatus.classList.add(`labeled-${decision.toLowerCase().replace('_','')}`);
  } else {
    el.badgeStatus.textContent = 'UNLABELED';
  }

  if (dirty) {
    S.dirty = true;
    setStatus('Unsaved', 'unsaved');
  }
}

function getDecision() {
  const btn = document.querySelector('.dec-btn.active');
  return btn ? btn.dataset.decision : null;
}

function populateDecision() {
  const item  = S.cases[S.idx];
  const label = S.annotations[item.case_id] || item.current_label || {};

  S.cited.clear();
  if (label.gold_clause_ids) {
    const list = Array.isArray(label.gold_clause_ids)
      ? label.gold_clause_ids
      : String(label.gold_clause_ids).split(/[,;]/);
    list.forEach(c => { if (c.trim()) S.cited.add(c.trim()); });
  }
  renderCitedTags();
  setDecision(label.gold_decision || null, false);

  if (label.gold_missing_evidence) {
    el.missingPills.forEach(p => p.classList.toggle('active', p.dataset.val === label.gold_missing_evidence));
  }
  if (label.gold_required_authority) {
    el.authPills.forEach(p => p.classList.toggle('active', p.dataset.val === label.gold_required_authority));
  }
  el.userReplyInput.value = label.user_response_text || '';
  el.notesArea.value      = label.notes || '';
  S.dirty = false;
  setStatus('Ready', '');
}

// ── Save ─────────────────────────────────────────────
async function saveCurrent() {
  const item = S.cases[S.idx];
  if (!item) return;
  const decision = getDecision();
  if (!decision) return;

  const activeMissing = document.querySelector('#missingPills .pill.active');
  const activeAuth    = document.querySelector('#authPills .pill.active');

  const label = {
    case_id:                item.case_id,
    gold_decision:          decision,
    gold_final_action:      (decision === 'ALLOW' || decision === 'BLOCK') ? decision : 'ALLOW',
    gold_missing_evidence:  decision === 'ASK_USER'  ? (activeMissing?.dataset.val || 'user_intent') : '',
    gold_required_authority:decision === 'ESCALATE'  ? (activeAuth?.dataset.val    || 'manager')     : '',
    gold_clause_ids:        [...S.cited].join(', '),
    user_response_text:     el.userReplyInput.value.trim(),
    user_response_confirmed:'yes',
    notes:                  el.notesArea.value.trim(),
  };

  S.annotations[item.case_id] = label;
  item.current_label = label;

  try {
    await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: S.batchId, annotator: S.annotator, case_id: item.case_id, label }),
    });
    setStatus('Saved ✓', 'saved');
  } catch {
    setStatus('Offline', '');
  }

  S.dirty = false;
  updateProgress();
}

async function saveAndNext() {
  await saveCurrent();
  if (S.idx < S.cases.length - 1) jump(S.idx + 1);
  else showToast('🎉 Batch complete! All cases labeled.');
}

function jump(idx) {
  if (idx < 0 || idx >= S.cases.length) return;
  if (S.dirty) saveCurrent();
  S.idx = idx;
  renderCase();
}

function nextUnlabeled() {
  if (S.dirty) saveCurrent();
  for (let i = S.idx + 1; i < S.cases.length; i++) {
    if (!S.annotations[S.cases[i].case_id]?.gold_decision) { jump(i); return; }
  }
  for (let i = 0; i <= S.idx; i++) {
    if (!S.annotations[S.cases[i].case_id]?.gold_decision) { jump(i); return; }
  }
  showToast('✅ All cases in this batch are labeled!');
}

// ── Progress ─────────────────────────────────────────
function updateProgress() {
  const total   = S.cases.length || 100;
  const labeled = Object.values(S.annotations).filter(a => a.gold_decision).length;
  const pct     = Math.round((labeled / total) * 100);
  el.progressLabel.textContent = `${labeled}/${total}`;
  el.progressBar.style.width   = `${pct}%`;
}

function setStatus(text, cls) {
  el.saveStatus.textContent = text;
  el.saveStatus.className   = `save-chip${cls ? ' ' + cls : ''}`;
}

function showToast(msg) {
  const t = document.createElement('div');
  t.style.cssText = `position:fixed;bottom:44px;left:50%;transform:translateX(-50%);
    background:#312e81;color:#c7d2fe;padding:10px 20px;border-radius:8px;
    font-size:13px;font-weight:600;z-index:9999;border:1px solid #6366f1;
    box-shadow:0 4px 20px rgba(99,102,241,0.4);animation:fadeIn .2s ease;`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ── Events ───────────────────────────────────────────
function bindEvents() {
  el.annotatorSelect.addEventListener('change', () => {
    S.annotator = el.annotatorSelect.value;
    localStorage.setItem('sagate_annotator', S.annotator);
    loadManifest().then(() => loadBatch(S.batchId));
  });

  el.batchSelect.addEventListener('change', () => {
    if (S.dirty) saveCurrent();
    loadBatch(el.batchSelect.value);
  });

  el.btnPrev.addEventListener('click', () => jump(S.idx - 1));
  el.btnNext.addEventListener('click', () => jump(S.idx + 1));
  el.btnSaveNext.addEventListener('click', saveAndNext);
  el.btnUnlabeled.addEventListener('click', nextUnlabeled);

  el.btnExport.addEventListener('click', () => {
    if (S.dirty) saveCurrent();
    window.open(`/api/export?batch_id=${S.batchId}&annotator=${S.annotator}`, '_blank');
  });

  document.querySelectorAll('.dec-btn').forEach(btn => {
    btn.addEventListener('click', () => setDecision(btn.dataset.decision));
  });

  el.missingPills.forEach(p => {
    p.addEventListener('click', () => {
      el.missingPills.forEach(x => x.classList.remove('active'));
      p.classList.add('active');
      S.dirty = true;
    });
  });

  el.authPills.forEach(p => {
    p.addEventListener('click', () => {
      el.authPills.forEach(x => x.classList.remove('active'));
      p.classList.add('active');
      S.dirty = true;
    });
  });

  window.addEventListener('keydown', e => {
    const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT';
    if (isInput) {
      if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); saveAndNext(); }
      return;
    }
    switch (e.key) {
      case '1': e.preventDefault(); setDecision('ALLOW'); break;
      case '2': e.preventDefault(); setDecision('BLOCK'); break;
      case '3': e.preventDefault(); setDecision('ASK_USER'); break;
      case '4': e.preventDefault(); setDecision('ESCALATE'); break;
      case 'Enter': e.preventDefault(); saveAndNext(); break;
      case 'ArrowLeft':  case '[': e.preventDefault(); jump(S.idx - 1); break;
      case 'ArrowRight': case ']': e.preventDefault(); jump(S.idx + 1); break;
      case 'u': case 'U': e.preventDefault(); nextUnlabeled(); break;
    }
  });
}

// ── Helpers ──────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#039;');
}

window.addEventListener('DOMContentLoaded', init);
