/**
 * SaGate Compact Reviewer Client
 */

const cState = {
  annotator: 'rinkesh',
  currentBatchId: 'batch_01',
  manifest: null,
  cases: [],
  currentIndex: 0,
  annotations: {},
  citedClauses: new Set(),
  dirty: false,
};

const cEl = {
  batchSelect: document.getElementById('compactBatchSelect'),
  annotatorSelect: document.getElementById('compactAnnotatorSelect'),
  progressLabel: document.getElementById('compactProgressLabel'),
  progressBar: document.getElementById('compactProgressBar'),
  btnUnlabeled: document.getElementById('compactBtnUnlabeled'),
  btnExport: document.getElementById('compactBtnExport'),
  prev: document.getElementById('compactPrev'),
  next: document.getElementById('compactNext'),
  caseNum: document.getElementById('compactCaseNum'),
  cBadgeSuite: document.getElementById('cBadgeSuite'),
  cBadgeCategory: document.getElementById('cBadgeCategory'),
  cBadgeDifficulty: document.getElementById('cBadgeDifficulty'),
  cBadgeStatus: document.getElementById('cBadgeStatus'),
  principal: document.getElementById('compactPrincipal'),
  prompt: document.getElementById('compactPrompt'),
  fnName: document.getElementById('compactFnName'),
  stateBadge: document.getElementById('compactStateBadge'),
  argsTable: document.getElementById('compactArgsTable'),
  authText: document.getElementById('compactAuthText'),
  flowText: document.getElementById('compactFlowText'),
  approverText: document.getElementById('compactApproverText'),
  untrustedSec: document.getElementById('compactUntrustedSec'),
  untrustedText: document.getElementById('compactUntrustedText'),
  policiesList: document.getElementById('compactPoliciesList'),
  saveStatus: document.getElementById('compactSaveStatus'),
  stackBtns: document.querySelectorAll('.stack-btn'),
  cAskDetails: document.getElementById('cAskDetails'),
  cEscalateDetails: document.getElementById('cEscalateDetails'),
  missingPills: document.querySelectorAll('#cMissingPills .c-pill'),
  authPills: document.querySelectorAll('#cAuthPills .c-pill'),
  userReplyText: document.getElementById('cUserReplyText'),
  citedTags: document.getElementById('compactCitedTags'),
  notes: document.getElementById('compactNotes'),
  saveNext: document.getElementById('compactSaveNext'),
};

async function cInit() {
  const saved = localStorage.getItem('sagate_annotator');
  if (saved) {
    cState.annotator = saved;
    cEl.annotatorSelect.value = saved;
  }

  setupEvents();
  await loadManifest();
  await loadBatch(cState.currentBatchId);
}

async function loadManifest() {
  try {
    const res = await fetch(`/api/manifest?annotator=${encodeURIComponent(cState.annotator)}`);
    cState.manifest = await res.json();
    cEl.batchSelect.innerHTML = '';
    (cState.manifest.batches || []).forEach((b) => {
      const opt = document.createElement('option');
      opt.value = b.batch_id;
      opt.textContent = `Batch ${b.batch_num.toString().padStart(2, '0')} (${b.labeled_count || 0}/${b.case_count})`;
      cEl.batchSelect.appendChild(opt);
    });
    cEl.batchSelect.value = cState.currentBatchId;
  } catch (err) {
    console.error('Error loading manifest:', err);
  }
}

async function loadBatch(batchId) {
  cState.currentBatchId = batchId;
  cEl.saveStatus.textContent = 'Loading...';

  try {
    const res = await fetch(`/api/batch?id=${batchId}&annotator=${encodeURIComponent(cState.annotator)}`);
    const data = await res.json();
    cState.cases = data.cases || [];
    cState.annotations = data.annotations || {};
  } catch (err) {
    console.error('Error loading batch:', err);
    return;
  }

  cState.currentIndex = 0;
  updateProgress();
  renderCase();
  cEl.saveStatus.textContent = 'Ready';
}

function renderCase() {
  if (!cState.cases || cState.cases.length === 0) return;

  const item = cState.cases[cState.currentIndex];
  const raw = item.raw_case || {};
  const inp = raw.input || {};

  cEl.caseNum.textContent = cState.currentIndex + 1;
  cEl.cBadgeSuite.textContent = item.suite || 'banking';
  cEl.cBadgeCategory.textContent = item.category || 'general';
  cEl.cBadgeDifficulty.textContent = item.difficulty || 'medium';

  cEl.principal.textContent = inp.user?.principal_id || 'user';
  cEl.prompt.textContent = inp.user?.prompt || '(No prompt)';

  const call = inp.proposed_call || {};
  cEl.fnName.textContent = `${call.function || 'unknown_tool'}()`;
  cEl.stateBadge.style.display = call.state_changing ? 'inline-block' : 'none';

  // Args
  renderArgs(call.args || {}, inp.provenance || []);

  // Security Context
  const auth = inp.authority || {};
  const sens = inp.sensitivity || {};
  cEl.authText.textContent = `${auth.principal || 'user'} (${auth.principal_role || 'role'})`;
  cEl.flowText.textContent = `${sens.resource || 'PUBLIC'} → ${sens.destination || 'INTERNAL'}`;
  cEl.approverText.textContent = auth.approver || 'None';

  // Untrusted
  const untrusted = inp.untrusted_content || [];
  if (untrusted.length > 0) {
    cEl.untrustedSec.style.display = 'block';
    cEl.untrustedText.textContent = untrusted.map((u) => `[${u.id} - ${u.source}]\n${u.text}`).join('\n\n');
  } else {
    cEl.untrustedSec.style.display = 'none';
  }

  // Policies
  renderPolicies(inp.policy_clauses || []);

  // Populate decision
  populateForm();
}

function renderArgs(args, provenance) {
  cEl.argsTable.innerHTML = '';
  const provMap = {};
  provenance.forEach((p) => { if (p.arg) provMap[p.arg] = p; });

  const entries = Object.entries(args);
  if (entries.length === 0) {
    cEl.argsTable.innerHTML = '<tr><td colspan="3" style="color: var(--c-text-muted);">No arguments</td></tr>';
    return;
  }

  entries.forEach(([key, val]) => {
    const p = provMap[key];
    const trust = p?.trust || 'unknown';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="color: #cbd5e1; font-weight: 600;">${escapeHtml(key)}</td>
      <td style="color: #fff;">${escapeHtml(typeof val === 'object' ? JSON.stringify(val) : String(val))}</td>
      <td><span style="font-size: 10px; text-transform: uppercase; color: ${trust === 'trusted' ? 'var(--c-green)' : (trust === 'unknown' ? 'var(--c-text-muted)' : 'var(--c-rose)')}; font-weight: 700;">${trust}</span></td>
    `;
    cEl.argsTable.appendChild(tr);
  });
}

function renderPolicies(clauses) {
  cEl.policiesList.innerHTML = '';
  if (!clauses || clauses.length === 0) {
    cEl.policiesList.innerHTML = '<div style="color: var(--c-text-muted); font-size: 11px;">No policies retrieved.</div>';
    return;
  }

  clauses.forEach((c) => {
    const isCited = cState.citedClauses.has(c.id);
    const item = document.createElement('div');
    item.className = `compact-policy-item ${isCited ? 'cited' : ''}`;
    item.setAttribute('data-id', c.id);
    item.innerHTML = `
      <div class="c-pol-head">
        <span class="c-pol-id">${escapeHtml(c.id)}</span>
        <span class="c-pol-title">${escapeHtml(c.title)}</span>
        <button type="button" class="c-cite-btn">${isCited ? '✓ Cited' : '+ Cite'}</button>
      </div>
      <div class="c-pol-text">${escapeHtml(c.text)}</div>
    `;

    item.querySelector('.c-cite-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleCiteClause(c.id);
    });

    cEl.policiesList.appendChild(item);
  });
}

function toggleCiteClause(clauseId) {
  if (cState.citedClauses.has(clauseId)) {
    cState.citedClauses.delete(clauseId);
  } else {
    cState.citedClauses.add(clauseId);
  }
  renderCitedTags();
  document.querySelectorAll(`.compact-policy-item[data-id="${clauseId}"]`).forEach((item) => {
    const isCited = cState.citedClauses.has(clauseId);
    item.classList.toggle('cited', isCited);
    item.querySelector('.c-cite-btn').textContent = isCited ? '✓ Cited' : '+ Cite';
  });
  cState.dirty = true;
}

function renderCitedTags() {
  cEl.citedTags.innerHTML = '';
  if (cState.citedClauses.size === 0) {
    cEl.citedTags.innerHTML = '<span class="no-tags">No clauses cited</span>';
    return;
  }

  cState.citedClauses.forEach((cid) => {
    const pill = document.createElement('span');
    pill.className = 'c-tag-pill';
    pill.innerHTML = `${escapeHtml(cid)} <span data-id="${escapeHtml(cid)}">&times;</span>`;
    pill.querySelector('span').addEventListener('click', () => toggleCiteClause(cid));
    cEl.citedTags.appendChild(pill);
  });
}

function populateForm() {
  const currentCase = cState.cases[cState.currentIndex];
  const label = cState.annotations[currentCase.case_id] || currentCase.current_label || {};

  cState.citedClauses.clear();
  if (label.gold_clause_ids) {
    const list = Array.isArray(label.gold_clause_ids)
      ? label.gold_clause_ids
      : String(label.gold_clause_ids).split(/[,;]/);
    list.forEach((cid) => { if (cid.trim()) cState.citedClauses.add(cid.trim()); });
  }
  renderCitedTags();

  setDecision(label.gold_decision || null, false);

  if (label.gold_missing_evidence) {
    cEl.missingPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_missing_evidence));
  }
  if (label.gold_required_authority) {
    cEl.authPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_required_authority));
  }

  cEl.userReplyText.value = label.user_response_text || '';
  cEl.notes.value = label.notes || '';
  cState.dirty = false;
}

function setDecision(decision, markDirty = true) {
  cEl.stackBtns.forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-decision') === decision);
  });

  cEl.cAskDetails.style.display = decision === 'ASK_USER' ? 'block' : 'none';
  cEl.cEscalateDetails.style.display = decision === 'ESCALATE' ? 'block' : 'none';

  cEl.cBadgeStatus.className = 'c-tag tag-status';
  if (decision) {
    cEl.cBadgeStatus.textContent = decision;
    cEl.cBadgeStatus.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
  } else {
    cEl.cBadgeStatus.textContent = 'UNLABELED';
  }

  if (markDirty) {
    cState.dirty = true;
    cEl.saveStatus.textContent = 'Unsaved';
  }
}

function getDecision() {
  const active = document.querySelector('.stack-btn.active');
  return active ? active.getAttribute('data-decision') : null;
}

async function saveCurrent() {
  const currentCase = cState.cases[cState.currentIndex];
  if (!currentCase) return;

  const decision = getDecision();
  if (!decision) return;

  const activeMissing = document.querySelector('#cMissingPills .c-pill.active');
  const activeAuth = document.querySelector('#cAuthPills .c-pill.active');

  const labelData = {
    case_id: currentCase.case_id,
    gold_decision: decision,
    gold_final_action: (decision === 'ALLOW' || decision === 'BLOCK') ? decision : 'ALLOW',
    gold_missing_evidence: decision === 'ASK_USER' ? (activeMissing ? activeMissing.getAttribute('data-val') : 'user_intent') : '',
    gold_required_authority: decision === 'ESCALATE' ? (activeAuth ? activeAuth.getAttribute('data-val') : 'manager') : '',
    gold_clause_ids: Array.from(cState.citedClauses).join(', '),
    user_response_text: cEl.userReplyText.value.trim(),
    user_response_confirmed: 'yes',
    notes: cEl.notes.value.trim(),
  };

  cState.annotations[currentCase.case_id] = labelData;
  currentCase.current_label = labelData;

  try {
    await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_id: cState.currentBatchId,
        annotator: cState.annotator,
        case_id: currentCase.case_id,
        label: labelData,
      }),
    });
    cEl.saveStatus.textContent = 'Saved';
  } catch {
    cEl.saveStatus.textContent = 'Offline';
  }

  cState.dirty = false;
  updateProgress();
}

async function saveAndNext() {
  await saveCurrent();
  if (cState.currentIndex < cState.cases.length - 1) {
    jump(cState.currentIndex + 1);
  } else {
    alert('🎉 Batch complete!');
  }
}

function jump(idx) {
  if (idx < 0 || idx >= cState.cases.length) return;
  if (cState.dirty) saveCurrent();
  cState.currentIndex = idx;
  renderCase();
}

function nextUnlabeled() {
  if (cState.dirty) saveCurrent();
  for (let i = cState.currentIndex + 1; i < cState.cases.length; i++) {
    if (!cState.annotations[cState.cases[i].case_id]?.gold_decision) {
      jump(i);
      return;
    }
  }
  for (let i = 0; i <= cState.currentIndex; i++) {
    if (!cState.annotations[cState.cases[i].case_id]?.gold_decision) {
      jump(i);
      return;
    }
  }
  alert('All cases labeled in this batch!');
}

function updateProgress() {
  const total = cState.cases.length || 100;
  const labeled = Object.values(cState.annotations).filter((a) => a.gold_decision).length;
  const pct = Math.round((labeled / total) * 100);

  cEl.progressLabel.textContent = `${labeled}/${total} (${pct}%)`;
  cEl.progressBar.style.width = `${pct}%`;
}

function setupEvents() {
  cEl.annotatorSelect.addEventListener('change', () => {
    cState.annotator = cEl.annotatorSelect.value;
    localStorage.setItem('sagate_annotator', cState.annotator);
    loadManifest();
    loadBatch(cState.currentBatchId);
  });

  cEl.batchSelect.addEventListener('change', () => {
    if (cState.dirty) saveCurrent();
    loadBatch(cEl.batchSelect.value);
  });

  cEl.prev.addEventListener('click', () => jump(cState.currentIndex - 1));
  cEl.next.addEventListener('click', () => jump(cState.currentIndex + 1));
  cEl.saveNext.addEventListener('click', saveAndNext);
  cEl.btnUnlabeled.addEventListener('click', nextUnlabeled);

  cEl.btnExport.addEventListener('click', () => {
    if (cState.dirty) saveCurrent();
    window.open(`/api/export?batch_id=${cState.currentBatchId}&annotator=${cState.annotator}`, '_blank');
  });

  cEl.stackBtns.forEach((btn) => {
    btn.addEventListener('click', () => setDecision(btn.getAttribute('data-decision')));
  });

  cEl.missingPills.forEach((p) => {
    p.addEventListener('click', () => {
      cEl.missingPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      cState.dirty = true;
    });
  });

  cEl.authPills.forEach((p) => {
    p.addEventListener('click', () => {
      cEl.authPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      cState.dirty = true;
    });
  });

  window.addEventListener('keydown', (e) => {
    const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (isInput) {
      if (e.key === 'Enter' && e.ctrlKey) {
        e.preventDefault();
        saveAndNext();
      }
      return;
    }

    switch (e.key) {
      case '1': e.preventDefault(); setDecision('ALLOW'); break;
      case '2': e.preventDefault(); setDecision('BLOCK'); break;
      case '3': e.preventDefault(); setDecision('ASK_USER'); break;
      case '4': e.preventDefault(); setDecision('ESCALATE'); break;
      case 'Enter': e.preventDefault(); saveAndNext(); break;
      case '[':
      case 'ArrowLeft': e.preventDefault(); jump(cState.currentIndex - 1); break;
      case ']':
      case 'ArrowRight': e.preventDefault(); jump(cState.currentIndex + 1); break;
      case 'u':
      case 'U': e.preventDefault(); nextUnlabeled(); break;
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

window.addEventListener('DOMContentLoaded', cInit);
