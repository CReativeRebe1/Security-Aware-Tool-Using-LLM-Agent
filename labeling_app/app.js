/**
 * SaGate Annotator - High-Productivity Human Labelling Client
 */

// Application State
const state = {
  annotator: 'rinkesh',
  currentBatchId: 'batch_01',
  manifest: null,
  cases: [],
  currentIndex: 0,
  annotations: {}, // { [case_id]: labelData }
  drawerFilter: 'all', // 'all' | 'unlabeled' | 'labeled'
  citedClauses: new Set(),
  dirty: false,
};

// DOM Elements
const el = {
  annotatorSelect: document.getElementById('annotatorSelect'),
  customAnnotatorInput: document.getElementById('customAnnotatorInput'),
  batchSelect: document.getElementById('batchSelect'),
  batchProgressBar: document.getElementById('batchProgressBar'),
  batchProgressText: document.getElementById('batchProgressText'),
  
  // Navigation
  btnPrev: document.getElementById('btnPrev'),
  btnNext: document.getElementById('btnNext'),
  btnNextUnlabeled: document.getElementById('btnNextUnlabeled'),
  currentCaseNum: document.getElementById('currentCaseNum'),
  totalCasesNum: document.getElementById('totalCasesNum'),
  
  // Badges
  badgeSuite: document.getElementById('badgeSuite'),
  badgeCategory: document.getElementById('badgeCategory'),
  badgeDifficulty: document.getElementById('badgeDifficulty'),
  badgeRound: document.getElementById('badgeRound'),
  badgeCaseStatus: document.getElementById('badgeCaseStatus'),
  caseIdDisplay: document.getElementById('caseIdDisplay'),
  
  // View Toggle
  btnViewStructured: document.getElementById('btnViewStructured'),
  btnViewRaw: document.getElementById('btnViewRaw'),
  structuredView: document.getElementById('structuredView'),
  rawPromptView: document.getElementById('rawPromptView'),
  rawCaseText: document.getElementById('rawCaseText'),
  btnCopyRaw: document.getElementById('btnCopyRaw'),
  
  // Left Column Details
  userPromptText: document.getElementById('userPromptText'),
  principalDisplay: document.getElementById('principalDisplay'),
  fnNameDisplay: document.getElementById('fnNameDisplay'),
  stateChangingBadge: document.getElementById('stateChangingBadge'),
  actionTypeBadge: document.getElementById('actionTypeBadge'),
  argsTableBody: document.getElementById('argsTableBody'),
  authSummary: document.getElementById('authSummary'),
  sensSummary: document.getElementById('sensSummary'),
  approverSummary: document.getElementById('approverSummary'),
  untrustedSection: document.getElementById('untrustedSection'),
  untrustedList: document.getElementById('untrustedList'),
  policyClausesList: document.getElementById('policyClausesList'),
  resolutionHistorySection: document.getElementById('resolutionHistorySection'),
  resolutionHistoryList: document.getElementById('resolutionHistoryList'),
  
  // Right Column Form
  decisionCards: document.querySelectorAll('.decision-card'),
  askUserDetails: document.getElementById('askUserDetails'),
  escalateDetails: document.getElementById('escalateDetails'),
  finalActionSection: document.getElementById('finalActionSection'),
  missingEvidencePills: document.querySelectorAll('#missingEvidencePills .pill'),
  requiredAuthorityPills: document.querySelectorAll('#requiredAuthorityPills .pill'),
  btnFinalAllow: document.getElementById('btnFinalAllow'),
  btnFinalBlock: document.getElementById('btnFinalBlock'),
  userResponseTextInput: document.getElementById('userResponseTextInput'),
  btnUserConfYes: document.getElementById('btnUserConfYes'),
  btnUserConfNo: document.getElementById('btnUserConfNo'),
  citedClausesContainer: document.getElementById('citedClausesContainer'),
  clauseTagInput: document.getElementById('clauseTagInput'),
  notesInput: document.getElementById('notesInput'),
  btnSaveAndNext: document.getElementById('btnSaveAndNext'),
  btnClearLabel: document.getElementById('btnClearLabel'),
  saveStatusIndicator: document.getElementById('saveStatusIndicator'),
  
  // Drawer & Modals
  btnCaseDrawer: document.getElementById('btnCaseDrawer'),
  caseDrawer: document.getElementById('caseDrawer'),
  drawerOverlay: document.getElementById('drawerOverlay'),
  btnCloseDrawer: document.getElementById('btnCloseDrawer'),
  drawerCasesGrid: document.getElementById('drawerCasesGrid'),
  unlabeledFilterCount: document.getElementById('unlabeledFilterCount'),
  labeledFilterCount: document.getElementById('labeledFilterCount'),
  drawerFilterChips: document.querySelectorAll('.filter-chip'),
  
  btnExportCsv: document.getElementById('btnExportCsv'),
  btnHelp: document.getElementById('btnHelp'),
  shortcutsModal: document.getElementById('shortcutsModal'),
  btnCloseModal: document.getElementById('btnCloseModal'),
};

// =============================================================================
// Initialization
// =============================================================================

async function init() {
  setupEventListeners();
  loadSavedAnnotator();
  await loadManifest();
  await loadBatch(state.currentBatchId);
}

function loadSavedAnnotator() {
  const saved = localStorage.getItem('sagate_annotator');
  if (saved) {
    state.annotator = saved;
    if (['rinkesh', 'prabhash', 'shubham', 'yogendra'].includes(saved)) {
      el.annotatorSelect.value = saved;
    } else {
      el.annotatorSelect.value = 'custom';
      el.customAnnotatorInput.style.display = 'inline-block';
      el.customAnnotatorInput.value = saved;
    }
  }
}

// =============================================================================
// API Calls & Data Loading
// =============================================================================

async function loadManifest() {
  try {
    const res = await fetch(`/api/manifest?annotator=${encodeURIComponent(state.annotator)}`);
    if (!res.ok) throw new Error('Failed to fetch manifest');
    state.manifest = await res.json();
    populateBatchSelect(state.manifest.batches);
  } catch (err) {
    console.warn('API error loading manifest, falling back to static batch list:', err);
    populateBatchSelectFallback();
  }
}

function populateBatchSelect(batches) {
  el.batchSelect.innerHTML = '';
  batches.forEach((b) => {
    const opt = document.createElement('option');
    opt.value = b.batch_id;
    const labeled = b.labeled_count || 0;
    opt.textContent = `Batch ${b.batch_num.toString().padStart(2, '0')} (${labeled}/${b.case_count})`;
    el.batchSelect.appendChild(opt);
  });
  el.batchSelect.value = state.currentBatchId;
}

function populateBatchSelectFallback() {
  el.batchSelect.innerHTML = '';
  for (let i = 1; i <= 20; i++) {
    const bId = `batch_${i.toString().padStart(2, '0')}`;
    const opt = document.createElement('option');
    opt.value = bId;
    opt.textContent = `Batch ${i.toString().padStart(2, '0')} (100 cases)`;
    el.batchSelect.appendChild(opt);
  }
}

async function loadBatch(batchId) {
  state.currentBatchId = batchId;
  el.saveStatusIndicator.textContent = 'Loading batch...';

  try {
    const res = await fetch(`/api/batch?id=${batchId}&annotator=${encodeURIComponent(state.annotator)}`);
    if (!res.ok) throw new Error(`Batch fetch error ${res.status}`);
    const data = await res.json();
    state.cases = data.cases || [];
    state.annotations = data.annotations || {};
  } catch (err) {
    console.warn(`Falling back to direct json fetch for ${batchId}:`, err);
    try {
      const res = await fetch(`../data/synthetic_data/batches/${batchId}.json`);
      state.cases = await res.json();
      state.annotations = loadLocalStorageAnnotations(batchId);
    } catch (e2) {
      alert(`Could not load batch data for ${batchId}. Make sure python server is running.`);
      return;
    }
  }

  state.currentIndex = 0;
  updateBatchProgress();
  renderCurrentCase();
  renderDrawerGrid();
  el.saveStatusIndicator.textContent = 'Ready';
}

function loadLocalStorageAnnotations(batchId) {
  const key = `sagate_ann_${batchId}_${state.annotator}`;
  try {
    return JSON.parse(localStorage.getItem(key)) || {};
  } catch {
    return {};
  }
}

function saveLocalStorageAnnotations(batchId, annotations) {
  const key = `sagate_ann_${batchId}_${state.annotator}`;
  localStorage.setItem(key, JSON.stringify(annotations));
}

// =============================================================================
// Rendering Case Details
// =============================================================================

function renderCurrentCase() {
  if (!state.cases || state.cases.length === 0) return;

  const item = state.cases[state.currentIndex];
  const raw = item.raw_case || {};
  const inp = raw.input || {};
  const meta = item.raw_case?.meta || {};

  // Case Counter
  el.currentCaseNum.textContent = state.currentIndex + 1;
  el.totalCasesNum.textContent = state.cases.length;

  // Header Badges
  el.badgeSuite.textContent = item.suite || inp.suite || 'banking';
  el.badgeCategory.textContent = item.category || 'general';
  el.badgeDifficulty.textContent = item.difficulty || meta.difficulty || 'medium';
  el.badgeRound.textContent = `Round ${item.round ?? meta.round ?? 0}`;
  el.caseIdDisplay.textContent = item.case_id;

  // 1. User Prompt Card
  el.userPromptText.textContent = inp.user?.prompt || '(No prompt available)';
  el.principalDisplay.textContent = `principal: ${inp.user?.principal_id || 'user'}`;

  // 2. Proposed Tool Call
  const call = inp.proposed_call || {};
  el.fnNameDisplay.textContent = `${call.function || 'unknown_tool'}()`;
  el.stateChangingBadge.style.display = call.state_changing ? 'inline-flex' : 'none';
  el.actionTypeBadge.textContent = call.action || 'action';

  // Arguments Table with Provenance
  renderArgumentsTable(call.args || {}, inp.provenance || []);

  // 3. Security Summary
  renderSecuritySummary(inp.authority || {}, inp.sensitivity || {});

  // 4. Untrusted Content
  renderUntrustedContent(inp.untrusted_content || []);

  // 5. Retrieved Policy Clauses
  renderPolicyClauses(inp.policy_clauses || []);

  // 6. Resolution History
  renderResolutionHistory(inp.resolution_history || []);

  // 7. Raw Case Text
  el.rawCaseText.textContent = item.case_text || JSON.stringify(item, null, 2);

  // 8. Populate Annotation Form
  populateFormForCurrentCase();

  // Update Drawer Current Tile
  highlightCurrentDrawerTile();
}

function renderArgumentsTable(args, provenance) {
  el.argsTableBody.innerHTML = '';
  const provMap = {};
  provenance.forEach((p) => {
    if (p.arg) provMap[p.arg] = p;
  });

  const argEntries = Object.entries(args);
  if (argEntries.length === 0) {
    el.argsTableBody.innerHTML = `<tr><td colspan="3" style="color: var(--text-muted); text-align: center;">No arguments</td></tr>`;
    return;
  }

  argEntries.forEach(([argName, argVal]) => {
    const tr = document.createElement('tr');
    const p = provMap[argName];
    const trust = p?.trust || 'unknown';
    const sources = (p?.sources || []).join(', ') || 'none';

    let provBadgeClass = 'prov-unknown';
    if (trust === 'trusted') provBadgeClass = 'prov-trusted';
    else if (trust === 'third_party' || trust === 'injection') provBadgeClass = 'prov-untrusted';

    tr.innerHTML = `
      <td class="arg-name">${escapeHtml(argName)}</td>
      <td class="arg-val">${escapeHtml(typeof argVal === 'object' ? JSON.stringify(argVal) : String(argVal))}</td>
      <td>
        <span class="arg-prov-tag ${provBadgeClass}">${trust}</span>
        <span style="font-size: 11px; color: var(--text-muted); margin-left: 6px;">[src: ${escapeHtml(sources)}]</span>
      </td>
    `;
    el.argsTableBody.appendChild(tr);
  });
}

function renderSecuritySummary(auth, sens) {
  // Authority
  const principal = auth.principal || 'user';
  const role = auth.principal_role || 'current_user';
  const mayAuth = auth.user_may_authorize ? 'Authorized' : 'Unauthorized';
  el.authSummary.textContent = `${principal} (${role}) — ${mayAuth}`;

  // Sensitivity / IFC flow
  const rLabel = sens.resource || 'PUBLIC';
  const dLabel = sens.destination || 'INTERNAL';
  const flow = sens.flow || 'ok';
  el.sensSummary.textContent = `${rLabel} → ${dLabel} [${flow.toUpperCase()}]`;

  // Approver
  el.approverSummary.textContent = auth.approver || 'None required';
}

function renderUntrustedContent(untrustedList) {
  if (!untrustedList || untrustedList.length === 0) {
    el.untrustedSection.style.display = 'none';
    return;
  }
  el.untrustedSection.style.display = 'flex';
  el.untrustedList.innerHTML = '';

  untrustedList.forEach((u) => {
    const card = document.createElement('div');
    card.className = 'untrusted-card';
    card.innerHTML = `
      <div class="untrusted-header">
        <span>ID: ${escapeHtml(u.id)}</span>
        <span>Source: ${escapeHtml(u.source)}</span>
      </div>
      <div class="untrusted-body">${escapeHtml(u.text)}</div>
    `;
    el.untrustedList.appendChild(card);
  });
}

function renderPolicyClauses(clauses) {
  el.policyClausesList.innerHTML = '';
  if (!clauses || clauses.length === 0) {
    el.policyClausesList.innerHTML = `<div style="font-size: 12px; color: var(--text-muted);">No policy clauses retrieved.</div>`;
    return;
  }

  clauses.forEach((c) => {
    const card = document.createElement('div');
    card.className = 'policy-card';
    card.innerHTML = `
      <div class="policy-header">
        <span class="policy-id">${escapeHtml(c.id)}</span>
        <span class="policy-title">${escapeHtml(c.title)}</span>
        <button type="button" class="btn-cite-clause" data-id="${escapeHtml(c.id)}">+ Cite</button>
      </div>
      <div class="policy-text">${escapeHtml(c.text)}</div>
    `;
    el.policyClausesList.appendChild(card);
  });

  // Attach Cite listeners
  el.policyClausesList.querySelectorAll('.btn-cite-clause').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      addCitedClause(btn.getAttribute('data-id'));
    });
  });
}

function renderResolutionHistory(history) {
  if (!history || history.length === 0) {
    el.resolutionHistorySection.style.display = 'none';
    return;
  }
  el.resolutionHistorySection.style.display = 'flex';
  el.resolutionHistoryList.innerHTML = '';

  history.forEach((h) => {
    const card = document.createElement('div');
    card.className = 'policy-card';
    card.innerHTML = `
      <div class="policy-header">
        <span class="policy-id">Round ${h.round} (${escapeHtml(h.kind)})</span>
        <span class="policy-title">Response from: ${escapeHtml(h.responder || 'user')}</span>
      </div>
      <div class="policy-text">
        <strong>Reply:</strong> "${escapeHtml(h.response)}" 
        <span style="margin-left: 8px; color: var(--color-accent);">[Confirmed: ${h.confirmed ? 'YES' : 'NO'}]</span>
      </div>
    `;
    el.resolutionHistoryList.appendChild(card);
  });
}

// =============================================================================
// Labelling Form Management
// =============================================================================

function populateFormForCurrentCase() {
  const currentCase = state.cases[state.currentIndex];
  const caseId = currentCase.case_id;
  const label = state.annotations[caseId] || currentCase.current_label || {};

  // Reset form
  resetForm();

  // Set Decision
  if (label.gold_decision) {
    setDecision(label.gold_decision, false);
    updateCaseStatusBadge(label.gold_decision);
  } else {
    updateCaseStatusBadge(null);
  }

  // Set Missing Evidence
  if (label.gold_missing_evidence) {
    setMissingEvidence(label.gold_missing_evidence);
  }

  // Set Required Authority
  if (label.gold_required_authority) {
    setRequiredAuthority(label.gold_required_authority);
  }

  // Set Final Action
  if (label.gold_final_action) {
    setFinalAction(label.gold_final_action);
  }

  // User Response text & confirmed
  if (label.user_response_text) {
    el.userResponseTextInput.value = label.user_response_text;
  }
  if (label.user_response_confirmed !== undefined && label.user_response_confirmed !== null) {
    setUserConfirmed(label.user_response_confirmed ? 'yes' : 'no');
  }

  // Cited Clauses
  state.citedClauses.clear();
  if (label.gold_clause_ids) {
    const list = Array.isArray(label.gold_clause_ids)
      ? label.gold_clause_ids
      : String(label.gold_clause_ids).split(/[,;]/);
    list.forEach((cid) => {
      if (cid.trim()) state.citedClauses.add(cid.trim());
    });
  }
  renderCitedClausesTags();

  // Notes
  if (label.notes) {
    el.notesInput.value = label.notes;
  }

  state.dirty = false;
}

function resetForm() {
  el.decisionCards.forEach((c) => c.classList.remove('active'));
  el.askUserDetails.style.display = 'none';
  el.escalateDetails.style.display = 'none';
  el.finalActionSection.style.display = 'none';

  el.missingEvidencePills.forEach((p) => p.classList.remove('active'));
  el.requiredAuthorityPills.forEach((p) => p.classList.remove('active'));

  el.btnFinalAllow.classList.add('active');
  el.btnFinalBlock.classList.remove('active');

  el.userResponseTextInput.value = '';
  el.btnUserConfYes.classList.remove('active');
  el.btnUserConfNo.classList.remove('active');

  state.citedClauses.clear();
  renderCitedClausesTags();

  el.notesInput.value = '';
}

function setDecision(decision, markDirty = true) {
  el.decisionCards.forEach((c) => {
    c.classList.toggle('active', c.getAttribute('data-decision') === decision);
  });

  // Toggle conditional sections
  el.askUserDetails.style.display = decision === 'ASK_USER' ? 'flex' : 'none';
  el.escalateDetails.style.display = decision === 'ESCALATE' ? 'flex' : 'none';
  el.finalActionSection.style.display = (decision === 'ASK_USER' || decision === 'ESCALATE') ? 'flex' : 'none';

  // Automatically default final_action
  if (decision === 'ALLOW') {
    setFinalAction('ALLOW');
  } else if (decision === 'BLOCK') {
    setFinalAction('BLOCK');
  } else if (decision === 'ASK_USER' && !getSelectedMissingEvidence()) {
    // Default to user_intent
    setMissingEvidence('user_intent');
  } else if (decision === 'ESCALATE' && !getSelectedRequiredAuthority()) {
    // Default to manager
    setRequiredAuthority('manager');
  }

  updateCaseStatusBadge(decision);
  if (markDirty) {
    state.dirty = true;
    el.saveStatusIndicator.textContent = 'Unsaved changes';
    el.saveStatusIndicator.className = 'save-status unsaved';
  }
}

function getSelectedDecision() {
  const active = document.querySelector('.decision-card.active');
  return active ? active.getAttribute('data-decision') : null;
}

function setMissingEvidence(val) {
  el.missingEvidencePills.forEach((p) => {
    p.classList.toggle('active', p.getAttribute('data-val') === val);
  });
  state.dirty = true;
}

function getSelectedMissingEvidence() {
  const active = document.querySelector('#missingEvidencePills .pill.active');
  return active ? active.getAttribute('data-val') : null;
}

function setRequiredAuthority(val) {
  el.requiredAuthorityPills.forEach((p) => {
    p.classList.toggle('active', p.getAttribute('data-val') === val);
  });
  state.dirty = true;
}

function getSelectedRequiredAuthority() {
  const active = document.querySelector('#requiredAuthorityPills .pill.active');
  return active ? active.getAttribute('data-val') : null;
}

function setFinalAction(action) {
  el.btnFinalAllow.classList.toggle('active', action === 'ALLOW');
  el.btnFinalBlock.classList.toggle('active', action === 'BLOCK');
  state.dirty = true;
}

function getSelectedFinalAction() {
  const decision = getSelectedDecision();
  if (decision === 'ALLOW' || decision === 'BLOCK') return decision;
  return el.btnFinalAllow.classList.contains('active') ? 'ALLOW' : 'BLOCK';
}

function setUserConfirmed(val) {
  el.btnUserConfYes.classList.toggle('active', val === 'yes');
  el.btnUserConfNo.classList.toggle('active', val === 'no');
  state.dirty = true;
}

function getUserConfirmed() {
  if (el.btnUserConfYes.classList.contains('active')) return 'yes';
  if (el.btnUserConfNo.classList.contains('active')) return 'no';
  return '';
}

// =============================================================================
// Cited Policy Clauses Tags
// =============================================================================

function addCitedClause(clauseId) {
  if (!clauseId) return;
  state.citedClauses.add(clauseId.trim());
  renderCitedClausesTags();
  state.dirty = true;
}

function removeCitedClause(clauseId) {
  state.citedClauses.delete(clauseId);
  renderCitedClausesTags();
  state.dirty = true;
}

function renderCitedClausesTags() {
  // Clear old pills except the input
  const pills = el.citedClausesContainer.querySelectorAll('.tag-pill');
  pills.forEach((p) => p.remove());

  state.citedClauses.forEach((cid) => {
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.innerHTML = `
      ${escapeHtml(cid)}
      <span class="tag-remove" data-id="${escapeHtml(cid)}">&times;</span>
    `;
    el.citedClausesContainer.insertBefore(pill, el.clauseTagInput);
  });

  // Attach remove listeners
  el.citedClausesContainer.querySelectorAll('.tag-remove').forEach((btn) => {
    btn.addEventListener('click', () => {
      removeCitedClause(btn.getAttribute('data-id'));
    });
  });
}

function updateCaseStatusBadge(decision) {
  el.badgeCaseStatus.className = 'badge badge-status';
  if (!decision) {
    el.badgeCaseStatus.textContent = 'UNLABELED';
  } else {
    el.badgeCaseStatus.textContent = decision;
    el.badgeCaseStatus.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
  }
}

// =============================================================================
// Saving Annotation
// =============================================================================

async function saveCurrentAnnotation() {
  const currentCase = state.cases[state.currentIndex];
  if (!currentCase) return;

  const caseId = currentCase.case_id;
  const decision = getSelectedDecision();

  if (!decision) {
    // Nothing selected
    return;
  }

  const labelData = {
    case_id: caseId,
    gold_decision: decision,
    gold_final_action: getSelectedFinalAction(),
    gold_missing_evidence: decision === 'ASK_USER' ? getSelectedMissingEvidence() : '',
    gold_required_authority: decision === 'ESCALATE' ? getSelectedRequiredAuthority() : '',
    gold_clause_ids: Array.from(state.citedClauses).join(', '),
    user_response_text: el.userResponseTextInput.value.trim(),
    user_response_confirmed: getUserConfirmed(),
    notes: el.notesInput.value.trim(),
  };

  // Update in-memory state
  state.annotations[caseId] = labelData;
  currentCase.current_label = labelData;

  // LocalStorage fallback
  saveLocalStorageAnnotations(state.currentBatchId, state.annotations);

  // Send to Python server
  try {
    const res = await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_id: state.currentBatchId,
        annotator: state.annotator,
        case_id: caseId,
        label: labelData,
      }),
    });
    if (!res.ok) throw new Error(`Save failed: ${res.status}`);
    el.saveStatusIndicator.textContent = 'Saved to disk';
    el.saveStatusIndicator.className = 'save-status';
  } catch (err) {
    console.warn('API save error, saved locally:', err);
    el.saveStatusIndicator.textContent = 'Saved locally (offline)';
    el.saveStatusIndicator.className = 'save-status';
  }

  state.dirty = false;
  updateBatchProgress();
  updateDrawerTile(state.currentIndex, decision);
}

function clearCurrentAnnotation() {
  const currentCase = state.cases[state.currentIndex];
  if (!currentCase) return;

  const caseId = currentCase.case_id;
  delete state.annotations[caseId];
  currentCase.current_label = null;

  resetForm();
  updateCaseStatusBadge(null);
  updateBatchProgress();
  updateDrawerTile(state.currentIndex, null);

  // Save empty to server
  fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      batch_id: state.currentBatchId,
      annotator: state.annotator,
      case_id: caseId,
      label: {},
    }),
  }).catch(() => {});
}

// =============================================================================
// Navigation & Progress
// =============================================================================

function jumpToCase(index) {
  if (index < 0 || index >= state.cases.length) return;
  if (state.dirty) {
    saveCurrentAnnotation();
  }
  state.currentIndex = index;
  renderCurrentCase();
}

function prevCase() {
  if (state.currentIndex > 0) {
    jumpToCase(state.currentIndex - 1);
  }
}

function nextCase() {
  if (state.currentIndex < state.cases.length - 1) {
    jumpToCase(state.currentIndex + 1);
  }
}

async function saveAndNext() {
  await saveCurrentAnnotation();
  if (state.currentIndex < state.cases.length - 1) {
    jumpToCase(state.currentIndex + 1);
  } else {
    alert('🎉 Congratulations! You have reached the end of this batch!');
  }
}

function jumpToNextUnlabeled() {
  if (state.dirty) saveCurrentAnnotation();

  for (let i = state.currentIndex + 1; i < state.cases.length; i++) {
    const cid = state.cases[i].case_id;
    if (!state.annotations[cid]?.gold_decision) {
      jumpToCase(i);
      return;
    }
  }

  // Wrap around from beginning
  for (let i = 0; i <= state.currentIndex; i++) {
    const cid = state.cases[i].case_id;
    if (!state.annotations[cid]?.gold_decision) {
      jumpToCase(i);
      return;
    }
  }

  alert('All 100 cases in this batch are labeled!');
}

function updateBatchProgress() {
  const total = state.cases.length || 100;
  const labeled = Object.values(state.annotations).filter((a) => a.gold_decision).length;
  const pct = Math.round((labeled / total) * 100);

  el.batchProgressText.textContent = `${labeled} / ${total} labeled (${pct}%)`;
  el.batchProgressBar.style.width = `${pct}%`;

  el.labeledFilterCount.textContent = labeled;
  el.unlabeledFilterCount.textContent = total - labeled;
}

// =============================================================================
// Drawer (1-100 Cases Grid)
// =============================================================================

function renderDrawerGrid() {
  el.drawerCasesGrid.innerHTML = '';
  state.cases.forEach((c, idx) => {
    const cid = c.case_id;
    const ann = state.annotations[cid];
    const decision = ann?.gold_decision;

    const tile = document.createElement('div');
    tile.className = 'drawer-case-tile';
    tile.setAttribute('data-index', idx);
    tile.setAttribute('data-labeled', decision ? 'true' : 'false');

    if (decision) {
      tile.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
      tile.innerHTML = `<span>${idx + 1}</span><span class="tile-badge">${formatTileBadge(decision)}</span>`;
    } else {
      tile.innerHTML = `<span>${idx + 1}</span>`;
    }

    tile.addEventListener('click', () => {
      jumpToCase(idx);
      closeDrawer();
    });

    el.drawerCasesGrid.appendChild(tile);
  });

  applyDrawerFilter();
  highlightCurrentDrawerTile();
}

function formatTileBadge(decision) {
  switch (decision) {
    case 'ALLOW': return 'A';
    case 'BLOCK': return 'B';
    case 'ASK_USER': return 'AU';
    case 'ESCALATE': return 'ESC';
    default: return '';
  }
}

function updateDrawerTile(idx, decision) {
  const tile = el.drawerCasesGrid.querySelector(`.drawer-case-tile[data-index="${idx}"]`);
  if (!tile) return;

  tile.className = 'drawer-case-tile';
  tile.setAttribute('data-labeled', decision ? 'true' : 'false');

  if (decision) {
    tile.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
    tile.innerHTML = `<span>${idx + 1}</span><span class="tile-badge">${formatTileBadge(decision)}</span>`;
  } else {
    tile.innerHTML = `<span>${idx + 1}</span>`;
  }

  highlightCurrentDrawerTile();
  applyDrawerFilter();
}

function highlightCurrentDrawerTile() {
  const tiles = el.drawerCasesGrid.querySelectorAll('.drawer-case-tile');
  tiles.forEach((t) => {
    const idx = parseInt(t.getAttribute('data-index'), 10);
    t.classList.toggle('current', idx === state.currentIndex);
  });
}

function applyDrawerFilter() {
  const tiles = el.drawerCasesGrid.querySelectorAll('.drawer-case-tile');
  tiles.forEach((t) => {
    const isLabeled = t.getAttribute('data-labeled') === 'true';
    if (state.drawerFilter === 'all') {
      t.style.display = 'flex';
    } else if (state.drawerFilter === 'labeled') {
      t.style.display = isLabeled ? 'flex' : 'none';
    } else if (state.drawerFilter === 'unlabeled') {
      t.style.display = !isLabeled ? 'flex' : 'none';
    }
  });
}

function openDrawer() {
  el.caseDrawer.classList.add('open');
  el.drawerOverlay.classList.add('active');
  highlightCurrentDrawerTile();
}

function closeDrawer() {
  el.caseDrawer.classList.remove('open');
  el.drawerOverlay.classList.remove('active');
}

// =============================================================================
// Exporting CSV
// =============================================================================

function exportBatchCsv() {
  if (state.dirty) saveCurrentAnnotation();
  const url = `/api/export?batch_id=${encodeURIComponent(state.currentBatchId)}&annotator=${encodeURIComponent(state.annotator)}`;
  window.open(url, '_blank');
}

// =============================================================================
// Event Listeners & Shortcuts
// =============================================================================

function setupEventListeners() {
  // Annotator Change
  el.annotatorSelect.addEventListener('change', () => {
    if (el.annotatorSelect.value === 'custom') {
      el.customAnnotatorInput.style.display = 'inline-block';
      el.customAnnotatorInput.focus();
    } else {
      el.customAnnotatorInput.style.display = 'none';
      state.annotator = el.annotatorSelect.value;
      localStorage.setItem('sagate_annotator', state.annotator);
      loadManifest();
      loadBatch(state.currentBatchId);
    }
  });

  el.customAnnotatorInput.addEventListener('change', () => {
    const val = el.customAnnotatorInput.value.trim().toLowerCase();
    if (val) {
      state.annotator = val;
      localStorage.setItem('sagate_annotator', state.annotator);
      loadManifest();
      loadBatch(state.currentBatchId);
    }
  });

  // Batch Select Change
  el.batchSelect.addEventListener('change', () => {
    if (state.dirty) saveCurrentAnnotation();
    loadBatch(el.batchSelect.value);
  });

  // Navigation
  el.btnPrev.addEventListener('click', prevCase);
  el.btnNext.addEventListener('click', nextCase);
  el.btnNextUnlabeled.addEventListener('click', jumpToNextUnlabeled);
  el.btnSaveAndNext.addEventListener('click', saveAndNext);
  el.btnClearLabel.addEventListener('click', clearCurrentAnnotation);
  el.btnExportCsv.addEventListener('click', exportBatchCsv);

  // Copy Case ID
  el.caseIdDisplay.addEventListener('click', () => {
    navigator.clipboard.writeText(el.caseIdDisplay.textContent);
    const orig = el.caseIdDisplay.textContent;
    el.caseIdDisplay.textContent = 'Copied to clipboard!';
    setTimeout(() => { el.caseIdDisplay.textContent = orig; }, 1200);
  });

  // View Toggle (Structured vs Raw)
  el.btnViewStructured.addEventListener('click', () => {
    el.btnViewStructured.classList.add('active');
    el.btnViewRaw.classList.remove('active');
    el.structuredView.classList.add('active');
    el.rawPromptView.classList.remove('active');
  });

  el.btnViewRaw.addEventListener('click', () => {
    el.btnViewRaw.classList.add('active');
    el.btnViewStructured.classList.remove('active');
    el.rawPromptView.classList.add('active');
    el.structuredView.classList.remove('active');
  });

  el.btnCopyRaw.addEventListener('click', () => {
    navigator.clipboard.writeText(el.rawCaseText.textContent);
    el.btnCopyRaw.textContent = 'Copied!';
    setTimeout(() => { el.btnCopyRaw.textContent = 'Copy Text'; }, 1200);
  });

  // Decision Card Clicks
  el.decisionCards.forEach((card) => {
    card.addEventListener('click', () => {
      setDecision(card.getAttribute('data-decision'));
    });
  });

  // Pills
  el.missingEvidencePills.forEach((p) => {
    p.addEventListener('click', () => {
      setMissingEvidence(p.getAttribute('data-val'));
    });
  });

  el.requiredAuthorityPills.forEach((p) => {
    p.addEventListener('click', () => {
      setRequiredAuthority(p.getAttribute('data-val'));
    });
  });

  el.btnFinalAllow.addEventListener('click', () => setFinalAction('ALLOW'));
  el.btnFinalBlock.addEventListener('click', () => setFinalAction('BLOCK'));

  el.btnUserConfYes.addEventListener('click', () => setUserConfirmed('yes'));
  el.btnUserConfNo.addEventListener('click', () => setUserConfirmed('no'));

  // Tag Input for Policy Clauses
  el.clauseTagInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const val = el.clauseTagInput.value.trim().toUpperCase();
      if (val) {
        addCitedClause(val);
        el.clauseTagInput.value = '';
      }
    }
  });

  // Drawer Toggle
  el.btnCaseDrawer.addEventListener('click', openDrawer);
  el.btnCloseDrawer.addEventListener('click', closeDrawer);
  el.drawerOverlay.addEventListener('click', closeDrawer);

  el.drawerFilterChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      el.drawerFilterChips.forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      state.drawerFilter = chip.getAttribute('data-filter');
      applyDrawerFilter();
    });
  });

  // Help Modal
  el.btnHelp.addEventListener('click', () => el.shortcutsModal.classList.add('active'));
  el.btnCloseModal.addEventListener('click', () => el.shortcutsModal.classList.remove('active'));
  el.shortcutsModal.addEventListener('click', (e) => {
    if (e.target === el.shortcutsModal) el.shortcutsModal.classList.remove('active');
  });

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', handleGlobalKeydown);
}

function handleGlobalKeydown(e) {
  // Ignore shortcuts when user is typing in text inputs or textareas
  const tag = e.target.tagName.toLowerCase();
  const isInput = tag === 'input' || tag === 'textarea';

  if (isInput) {
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault();
      saveAndNext();
    }
    return;
  }

  switch (e.key) {
    case '1':
      e.preventDefault();
      setDecision('ALLOW');
      break;
    case '2':
      e.preventDefault();
      setDecision('BLOCK');
      break;
    case '3':
      e.preventDefault();
      setDecision('ASK_USER');
      break;
    case '4':
      e.preventDefault();
      setDecision('ESCALATE');
      break;
    case 'Enter':
      e.preventDefault();
      saveAndNext();
      break;
    case '[':
    case 'ArrowLeft':
      e.preventDefault();
      prevCase();
      break;
    case ']':
    case 'ArrowRight':
      e.preventDefault();
      nextCase();
      break;
    case 'u':
    case 'U':
      e.preventDefault();
      jumpToNextUnlabeled();
      break;
    case 'g':
    case 'G':
      e.preventDefault();
      el.caseDrawer.classList.contains('open') ? closeDrawer() : openDrawer();
      break;
    case 'r':
    case 'R':
      e.preventDefault();
      if (el.structuredView.classList.contains('active')) {
        el.btnViewRaw.click();
      } else {
        el.btnViewStructured.click();
      }
      break;
    case '?':
      e.preventDefault();
      el.shortcutsModal.classList.toggle('active');
      break;
    case 'Escape':
      closeDrawer();
      el.shortcutsModal.classList.remove('active');
      break;
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Start application
window.addEventListener('DOMContentLoaded', init);
