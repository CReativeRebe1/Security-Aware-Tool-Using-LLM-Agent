/**
 * SaGate Structured Form / Wireframe Client Logic
 */

const wfState = {
  annotator: 'rinkesh',
  currentBatchId: 'batch_01',
  manifest: null,
  cases: [],
  currentIndex: 0,
  annotations: {},
  citedClauses: new Set(),
  dirty: false,
};

const wfEl = {
  progressPill: document.getElementById('wfProgressPill'),
  currentIdx: document.getElementById('wfCurrentIdx'),
  totalCount: document.getElementById('wfTotalCount'),
  prevBtn: document.getElementById('wfPrevBtn'),
  nextBtn: document.getElementById('wfNextBtn'),
  suiteChip: document.getElementById('wfSuiteChip'),
  categoryChip: document.getElementById('wfCategoryChip'),
  diffChip: document.getElementById('wfDiffChip'),
  statusChip: document.getElementById('wfStatusChip'),
  batchSelect: document.getElementById('wfBatchSelect'),
  annotatorSelect: document.getElementById('wfAnnotatorSelect'),
  principal: document.getElementById('wfPrincipal'),
  prompt: document.getElementById('wfPrompt'),
  fnBadge: document.getElementById('wfFnBadge'),
  argsTableBody: document.getElementById('wfArgsTableBody'),
  stateChangingTag: document.getElementById('wfStateChangingTag'),
  authData: document.getElementById('wfAuthData'),
  flowData: document.getElementById('wfFlowData'),
  approverData: document.getElementById('wfApproverData'),
  untrustedCard: document.getElementById('wfUntrustedCard'),
  untrustedGrid: document.getElementById('wfUntrustedGrid'),
  policiesList: document.getElementById('wfPoliciesList'),
  decBtns: document.querySelectorAll('.wf-dec-btn'),
  askBox: document.getElementById('wfAskBox'),
  escalateBox: document.getElementById('wfEscalateBox'),
  missingPills: document.querySelectorAll('#wfMissingPills .wf-cond-pill'),
  authPills: document.querySelectorAll('#wfAuthPills .wf-cond-pill'),
  userReplyInput: document.getElementById('wfUserReplyInput'),
  replyCharCount: document.getElementById('wfReplyCharCount'),
  citedTags: document.getElementById('wfCitedTags'),
  addClauseInput: document.getElementById('wfAddClauseInput'),
  btnAddClause: document.getElementById('wfBtnAddClause'),
  notesInput: document.getElementById('wfNotesInput'),
  notesCharCount: document.getElementById('wfNotesCharCount'),
  saveNextBtn: document.getElementById('wfSaveNextBtn'),
  saveStatus: document.getElementById('wfSaveStatus'),
};

async function wfInit() {
  const saved = localStorage.getItem('sagate_annotator');
  if (saved) {
    wfState.annotator = saved;
    wfEl.annotatorSelect.value = saved;
  }

  setupWfEvents();
  await wfLoadManifest();
  await wfLoadBatch(wfState.currentBatchId);
}

async function wfLoadManifest() {
  try {
    const res = await fetch(`/api/manifest?annotator=${encodeURIComponent(wfState.annotator)}`);
    wfState.manifest = await res.json();
    wfEl.batchSelect.innerHTML = '';
    (wfState.manifest.batches || []).forEach((b) => {
      const opt = document.createElement('option');
      opt.value = b.batch_id;
      opt.textContent = `Batch ${b.batch_num.toString().padStart(2, '0')} (${b.labeled_count || 0}/${b.case_count})`;
      wfEl.batchSelect.appendChild(opt);
    });
    wfEl.batchSelect.value = wfState.currentBatchId;
  } catch (err) {
    console.error('Error loading manifest:', err);
  }
}

async function wfLoadBatch(batchId) {
  wfState.currentBatchId = batchId;
  wfEl.saveStatus.textContent = 'Loading batch...';

  try {
    const res = await fetch(`/api/batch?id=${batchId}&annotator=${encodeURIComponent(wfState.annotator)}`);
    const data = await res.json();
    wfState.cases = data.cases || [];
    wfState.annotations = data.annotations || {};
  } catch (err) {
    console.error('Error loading batch:', err);
    return;
  }

  wfState.currentIndex = 0;
  wfUpdateProgress();
  wfRenderCase();
  wfEl.saveStatus.textContent = 'Auto-saved to local SQLite & JSON/CSV';
}

function wfRenderCase() {
  if (!wfState.cases || wfState.cases.length === 0) return;

  const item = wfState.cases[wfState.currentIndex];
  const raw = item.raw_case || {};
  const inp = raw.input || {};
  const meta = item.raw_case?.meta || {};

  wfEl.currentIdx.textContent = wfState.currentIndex + 1;
  wfEl.totalCount.textContent = wfState.cases.length;

  wfEl.suiteChip.textContent = `🌐 suite=${item.suite || 'banking'}`;
  wfEl.categoryChip.textContent = `🔒 category=${item.category || 'general'}`;
  wfEl.diffChip.textContent = `💼 difficulty=${item.difficulty || 'medium'}`;

  // 1. User Request
  wfEl.principal.textContent = inp.user?.principal_id || 'bank-app-service';
  wfEl.prompt.textContent = inp.user?.prompt || '(No prompt)';

  // 2. Proposed Tool Call
  const call = inp.proposed_call || {};
  wfEl.fnBadge.textContent = call.function ? `${call.function}` : 'unknown_function';
  wfEl.stateChangingTag.textContent = `state-changing: ${call.state_changing ? 'yes' : 'no'}`;

  wfRenderArgs(call.args || {}, inp.provenance || []);

  // 3. Security Context
  const auth = inp.authority || {};
  const sens = inp.sensitivity || {};
  wfEl.authData.textContent = `${auth.principal || 'user'} (${auth.principal_role || 'role'})`;
  wfEl.flowData.textContent = `${sens.resource || 'PUBLIC'} → ${sens.destination || 'INTERNAL'}`;
  wfEl.approverData.textContent = auth.approver || '—';

  // 4. Untrusted Content
  const untrusted = inp.untrusted_content || [];
  if (untrusted.length > 0) {
    wfEl.untrustedCard.style.display = 'flex';
    wfEl.untrustedGrid.innerHTML = '';
    untrusted.slice(0, 2).forEach((u, idx) => {
      const box = document.createElement('div');
      box.className = 'wf-untrusted-box';
      box.innerHTML = `
        <span class="box-num">${idx + 1}</span>
        <span class="box-source">Source: ${escapeHtml(u.source)}</span>
        <div class="box-snippet">${escapeHtml(u.text)}</div>
      `;
      wfEl.untrustedGrid.appendChild(box);
    });
  } else {
    wfEl.untrustedCard.style.display = 'none';
  }

  // 5. Policy Clauses
  wfRenderPolicies(inp.policy_clauses || []);

  // Form State
  wfPopulateForm();
}

function wfRenderArgs(args, provenance) {
  wfEl.argsTableBody.innerHTML = '';
  const provMap = {};
  provenance.forEach((p) => { if (p.arg) provMap[p.arg] = p; });

  const entries = Object.entries(args);
  if (entries.length === 0) {
    wfEl.argsTableBody.innerHTML = '<tr><td colspan="3" style="color: var(--wf-text-dim); text-align: center;">No arguments</td></tr>';
    return;
  }

  entries.forEach(([arg, val]) => {
    const p = provMap[arg];
    const trust = p?.trust || 'unknown';
    const sources = (p?.sources || []).join(', ') || 'prompt';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="color: #cbd5e1; font-weight: 600;">${escapeHtml(arg)}</td>
      <td style="color: #fff;">${escapeHtml(typeof val === 'object' ? JSON.stringify(val) : String(val))}</td>
      <td style="color: ${trust === 'trusted' ? 'var(--wf-allow)' : (trust === 'unknown' ? 'var(--wf-text-dim)' : 'var(--wf-block)')}; font-weight: 600;">
        ${escapeHtml(sources)} (${trust})
      </td>
    `;
    wfEl.argsTableBody.appendChild(tr);
  });
}

function wfRenderPolicies(clauses) {
  wfEl.policiesList.innerHTML = '';
  if (!clauses || clauses.length === 0) {
    wfEl.policiesList.innerHTML = '<div style="color: var(--wf-text-dim); font-size: 11px;">No policy clauses retrieved.</div>';
    return;
  }

  clauses.forEach((c) => {
    const isCited = wfState.citedClauses.has(c.id);
    const row = document.createElement('div');
    row.className = `wf-policy-row ${isCited ? 'cited' : ''}`;
    row.setAttribute('data-id', c.id);
    row.innerHTML = `
      <div class="wf-policy-left">
        <span class="wf-check-icon">${isCited ? '✓' : '○'}</span>
        <span class="wf-policy-id">${escapeHtml(c.id)}</span>
        <span class="wf-policy-text">"${escapeHtml(c.text)}"</span>
      </div>
      <button type="button" class="wf-btn-cite">${isCited ? '✓ Cited' : '+ Cite'}</button>
    `;

    row.querySelector('.wf-btn-cite').addEventListener('click', (e) => {
      e.stopPropagation();
      wfToggleCite(c.id);
    });

    wfEl.policiesList.appendChild(row);
  });
}

function wfToggleCite(clauseId) {
  if (wfState.citedClauses.has(clauseId)) {
    wfState.citedClauses.delete(clauseId);
  } else {
    wfState.citedClauses.add(clauseId);
  }
  wfRenderCitedTags();
  document.querySelectorAll(`.wf-policy-row[data-id="${clauseId}"]`).forEach((row) => {
    const isCited = wfState.citedClauses.has(clauseId);
    row.classList.toggle('cited', isCited);
    row.querySelector('.wf-check-icon').textContent = isCited ? '✓' : '○';
    row.querySelector('.wf-btn-cite').textContent = isCited ? '✓ Cited' : '+ Cite';
  });
  wfState.dirty = true;
}

function wfRenderCitedTags() {
  wfEl.citedTags.innerHTML = '';
  if (wfState.citedClauses.size === 0) {
    wfEl.citedTags.innerHTML = '<span class="wf-no-tags">(none cited)</span>';
    return;
  }

  wfState.citedClauses.forEach((cid) => {
    const badge = document.createElement('span');
    badge.className = 'wf-tag-badge';
    badge.innerHTML = `${escapeHtml(cid)} <span data-id="${escapeHtml(cid)}">&times;</span>`;
    badge.querySelector('span').addEventListener('click', () => wfToggleCite(cid));
    wfEl.citedTags.appendChild(badge);
  });
}

function wfPopulateForm() {
  const currentCase = wfState.cases[wfState.currentIndex];
  const label = wfState.annotations[currentCase.case_id] || currentCase.current_label || {};

  wfState.citedClauses.clear();
  if (label.gold_clause_ids) {
    const list = Array.isArray(label.gold_clause_ids)
      ? label.gold_clause_ids
      : String(label.gold_clause_ids).split(/[,;]/);
    list.forEach((cid) => { if (cid.trim()) wfState.citedClauses.add(cid.trim()); });
  }
  wfRenderCitedTags();

  wfSetDecision(label.gold_decision || null, false);

  if (label.gold_missing_evidence) {
    wfEl.missingPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_missing_evidence));
  }
  if (label.gold_required_authority) {
    wfEl.authPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_required_authority));
  }

  wfEl.userReplyInput.value = label.user_response_text || '';
  wfEl.replyCharCount.textContent = wfEl.userReplyInput.value.length;

  wfEl.notesInput.value = label.notes || '';
  wfEl.notesCharCount.textContent = wfEl.notesInput.value.length;

  wfState.dirty = false;
}

function wfSetDecision(decision, markDirty = true) {
  wfEl.decBtns.forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-decision') === decision);
  });

  wfEl.askBox.style.display = decision === 'ASK_USER' ? 'flex' : 'none';
  wfEl.escalateBox.style.display = decision === 'ESCALATE' ? 'flex' : 'none';

  wfEl.statusChip.className = 'wf-chip wf-status-chip';
  if (decision) {
    wfEl.statusChip.textContent = `✓ status=${decision}`;
    wfEl.statusChip.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
  } else {
    wfEl.statusChip.textContent = '✓ status=UNLABELED';
  }

  if (markDirty) {
    wfState.dirty = true;
    wfEl.saveStatus.textContent = 'Unsaved changes...';
  }
}

function wfGetDecision() {
  const active = document.querySelector('.wf-dec-btn.active');
  return active ? active.getAttribute('data-decision') : null;
}

async function wfSave() {
  const currentCase = wfState.cases[wfState.currentIndex];
  if (!currentCase) return;

  const decision = wfGetDecision();
  if (!decision) return;

  const activeMissing = document.querySelector('#wfMissingPills .wf-cond-pill.active');
  const activeAuth = document.querySelector('#wfAuthPills .wf-cond-pill.active');

  const labelData = {
    case_id: currentCase.case_id,
    gold_decision: decision,
    gold_final_action: (decision === 'ALLOW' || decision === 'BLOCK') ? decision : 'ALLOW',
    gold_missing_evidence: decision === 'ASK_USER' ? (activeMissing ? activeMissing.getAttribute('data-val') : 'user_intent') : '',
    gold_required_authority: decision === 'ESCALATE' ? (activeAuth ? activeAuth.getAttribute('data-val') : 'manager') : '',
    gold_clause_ids: Array.from(wfState.citedClauses).join(', '),
    user_response_text: wfEl.userReplyInput.value.trim(),
    user_response_confirmed: 'yes',
    notes: wfEl.notesInput.value.trim(),
  };

  wfState.annotations[currentCase.case_id] = labelData;
  currentCase.current_label = labelData;

  try {
    await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_id: wfState.currentBatchId,
        annotator: wfState.annotator,
        case_id: currentCase.case_id,
        label: labelData,
      }),
    });
    wfEl.saveStatus.textContent = 'Auto-saved to local SQLite & JSON/CSV';
  } catch {
    wfEl.saveStatus.textContent = 'Saved locally in browser';
  }

  wfState.dirty = false;
  wfUpdateProgress();
}

async function wfSaveAndNext() {
  await wfSave();
  if (wfState.currentIndex < wfState.cases.length - 1) {
    wfJump(wfState.currentIndex + 1);
  } else {
    alert('🎉 Batch complete!');
  }
}

function wfJump(idx) {
  if (idx < 0 || idx >= wfState.cases.length) return;
  if (wfState.dirty) wfSave();
  wfState.currentIndex = idx;
  wfRenderCase();
}

function wfUpdateProgress() {
  const total = wfState.cases.length || 100;
  const labeled = Object.values(wfState.annotations).filter((a) => a.gold_decision).length;
  wfEl.progressPill.textContent = `${labeled}/${total} labeled`;
}

function setupWfEvents() {
  wfEl.annotatorSelect.addEventListener('change', () => {
    wfState.annotator = wfEl.annotatorSelect.value;
    localStorage.setItem('sagate_annotator', wfState.annotator);
    wfLoadManifest();
    wfLoadBatch(wfState.currentBatchId);
  });

  wfEl.batchSelect.addEventListener('change', () => {
    if (wfState.dirty) wfSave();
    wfLoadBatch(wfEl.batchSelect.value);
  });

  wfEl.prevBtn.addEventListener('click', () => wfJump(wfState.currentIndex - 1));
  wfEl.nextBtn.addEventListener('click', () => wfJump(wfState.currentIndex + 1));
  wfEl.saveNextBtn.addEventListener('click', wfSaveAndNext);

  wfEl.decBtns.forEach((btn) => {
    btn.addEventListener('click', () => wfSetDecision(btn.getAttribute('data-decision')));
  });

  wfEl.missingPills.forEach((p) => {
    p.addEventListener('click', () => {
      wfEl.missingPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      wfState.dirty = true;
    });
  });

  wfEl.authPills.forEach((p) => {
    p.addEventListener('click', () => {
      wfEl.authPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      wfState.dirty = true;
    });
  });

  wfEl.userReplyInput.addEventListener('input', () => {
    wfEl.replyCharCount.textContent = wfEl.userReplyInput.value.length;
    wfState.dirty = true;
  });

  wfEl.notesInput.addEventListener('input', () => {
    wfEl.notesCharCount.textContent = wfEl.notesInput.value.length;
    wfState.dirty = true;
  });

  // Add custom clause
  wfEl.btnAddClause.addEventListener('click', () => {
    const val = wfEl.addClauseInput.value.trim().toUpperCase();
    if (val) {
      wfState.citedClauses.add(val);
      wfRenderCitedTags();
      wfEl.addClauseInput.value = '';
      wfState.dirty = true;
    }
  });

  window.addEventListener('keydown', (e) => {
    const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (isInput) {
      if (e.key === 'Enter' && e.ctrlKey) {
        e.preventDefault();
        wfSaveAndNext();
      }
      return;
    }

    switch (e.key) {
      case '1': e.preventDefault(); wfSetDecision('ALLOW'); break;
      case '2': e.preventDefault(); wfSetDecision('BLOCK'); break;
      case '3': e.preventDefault(); wfSetDecision('ASK_USER'); break;
      case '4': e.preventDefault(); wfSetDecision('ESCALATE'); break;
      case 'Enter': e.preventDefault(); wfSaveAndNext(); break;
      case '[':
      case 'ArrowLeft': e.preventDefault(); wfJump(wfState.currentIndex - 1); break;
      case ']':
      case 'ArrowRight': e.preventDefault(); wfJump(wfState.currentIndex + 1); break;
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

window.addEventListener('DOMContentLoaded', wfInit);
