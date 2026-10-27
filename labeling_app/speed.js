/**
 * SaGate Speed Triage Client
 */

const sState = {
  annotator: 'rinkesh',
  currentBatchId: 'batch_01',
  manifest: null,
  cases: [],
  currentIndex: 0,
  annotations: {},
  citedClauses: new Set(),
  dirty: false,
};

const sEl = {
  batchSelect: document.getElementById('sBatchSelect'),
  annotatorSelect: document.getElementById('sAnnotatorSelect'),
  progressBadge: document.getElementById('sProgressBadge'),
  btnExport: document.getElementById('sBtnExport'),
  btnNextUnlabeled: document.getElementById('sBtnNextUnlabeled'),
  queueList: document.getElementById('sQueueList'),
  caseNum: document.getElementById('sCaseNum'),
  suiteBadge: document.getElementById('sSuiteBadge'),
  categoryBadge: document.getElementById('sCategoryBadge'),
  diffBadge: document.getElementById('sDiffBadge'),
  statusIndicator: document.getElementById('sStatusIndicator'),
  principal: document.getElementById('sPrincipal'),
  promptText: document.getElementById('sPromptText'),
  fnTitle: document.getElementById('sFnTitle'),
  argsPills: document.getElementById('sArgsPills'),
  authChip: document.getElementById('sAuthChip'),
  flowChip: document.getElementById('sFlowChip'),
  approverChip: document.getElementById('sApproverChip'),
  untrustedAlert: document.getElementById('sUntrustedAlert'),
  untrustedBody: document.getElementById('sUntrustedBody'),
  policyList: document.getElementById('sPolicyList'),
  hudBtns: document.querySelectorAll('.hud-btn'),
  saveNextBtn: document.getElementById('sSaveNextBtn'),
  askDrawer: document.getElementById('sAskDrawer'),
  escalateDrawer: document.getElementById('sEscalateDrawer'),
  missingPills: document.querySelectorAll('#sMissingPills .sub-pill'),
  authPills: document.querySelectorAll('#sAuthPills .sub-pill'),
  citedTags: document.getElementById('sCitedTags'),
  saveStatus: document.getElementById('sSaveStatus'),
};

async function sInit() {
  const saved = localStorage.getItem('sagate_annotator');
  if (saved) {
    sState.annotator = saved;
    sEl.annotatorSelect.value = saved;
  }

  setupEvents();
  await loadManifest();
  await loadBatch(sState.currentBatchId);
}

async function loadManifest() {
  try {
    const res = await fetch(`/api/manifest?annotator=${encodeURIComponent(sState.annotator)}`);
    sState.manifest = await res.json();
    sEl.batchSelect.innerHTML = '';
    (sState.manifest.batches || []).forEach((b) => {
      const opt = document.createElement('option');
      opt.value = b.batch_id;
      opt.textContent = `Batch ${b.batch_num.toString().padStart(2, '0')} (${b.labeled_count || 0}/${b.case_count})`;
      sEl.batchSelect.appendChild(opt);
    });
    sEl.batchSelect.value = sState.currentBatchId;
  } catch (err) {
    console.error('Error loading manifest:', err);
  }
}

async function loadBatch(batchId) {
  sState.currentBatchId = batchId;
  sEl.saveStatus.textContent = 'Loading...';

  try {
    const res = await fetch(`/api/batch?id=${batchId}&annotator=${encodeURIComponent(sState.annotator)}`);
    const data = await res.json();
    sState.cases = data.cases || [];
    sState.annotations = data.annotations || {};
  } catch (err) {
    console.error('Error loading batch:', err);
    return;
  }

  sState.currentIndex = 0;
  updateProgress();
  renderQueue();
  renderCase();
  sEl.saveStatus.textContent = 'Ready';
}

function renderQueue() {
  sEl.queueList.innerHTML = '';
  sState.cases.forEach((c, idx) => {
    const ann = sState.annotations[c.case_id];
    const decision = ann?.gold_decision;

    const item = document.createElement('div');
    item.className = `queue-item ${idx === sState.currentIndex ? 'current' : ''}`;
    item.setAttribute('data-idx', idx);

    let badgeHtml = '';
    if (decision) {
      let bClass = 'badge-A';
      let bText = 'A';
      if (decision === 'BLOCK') { bClass = 'badge-B'; bText = 'B'; }
      else if (decision === 'ASK_USER') { bClass = 'badge-AU'; bText = 'AU'; }
      else if (decision === 'ESCALATE') { bClass = 'badge-ESC'; bText = 'ESC'; }
      badgeHtml = `<span class="item-badge ${bClass}">${bText}</span>`;
    }

    item.innerHTML = `
      <div class="item-left">
        <span class="item-idx">${idx + 1}</span>
        <span class="item-suite">${escapeHtml(c.suite || 'banking')}</span>
      </div>
      ${badgeHtml}
    `;

    item.addEventListener('click', () => jump(idx));
    sEl.queueList.appendChild(item);
  });
}

function renderCase() {
  if (!sState.cases || sState.cases.length === 0) return;

  const item = sState.cases[sState.currentIndex];
  const raw = item.raw_case || {};
  const inp = raw.input || {};

  sEl.caseNum.textContent = sState.currentIndex + 1;
  sEl.suiteBadge.textContent = item.suite || 'banking';
  sEl.categoryBadge.textContent = item.category || 'general';
  sEl.diffBadge.textContent = item.difficulty || 'medium';

  sEl.principal.textContent = inp.user?.principal_id || 'user';
  sEl.promptText.textContent = inp.user?.prompt || '(No prompt)';

  const call = inp.proposed_call || {};
  sEl.fnTitle.textContent = `${call.function || 'unknown_tool'}()`;

  // Render argument pills
  renderArgPills(call.args || {}, inp.provenance || []);

  // Security Context
  const auth = inp.authority || {};
  const sens = inp.sensitivity || {};
  sEl.authChip.textContent = `Auth: ${auth.principal || 'user'} (${auth.principal_role || 'role'})`;
  sEl.flowChip.textContent = `Flow: ${sens.resource || 'PUBLIC'} → ${sens.destination || 'INTERNAL'}`;
  sEl.approverChip.textContent = `Approver: ${auth.approver || 'None'}`;

  // Untrusted
  const untrusted = inp.untrusted_content || [];
  if (untrusted.length > 0) {
    sEl.untrustedAlert.style.display = 'block';
    sEl.untrustedBody.textContent = untrusted.map((u) => `[${u.id} - ${u.source}]\n${u.text}`).join('\n\n');
  } else {
    sEl.untrustedAlert.style.display = 'none';
  }

  // Policies
  renderPolicies(inp.policy_clauses || []);

  // Form
  populateForm();

  // Highlight queue item
  document.querySelectorAll('.queue-item').forEach((q, idx) => {
    q.classList.toggle('current', idx === sState.currentIndex);
  });
}

function renderArgPills(args, provenance) {
  sEl.argsPills.innerHTML = '';
  const provMap = {};
  provenance.forEach((p) => { if (p.arg) provMap[p.arg] = p; });

  const entries = Object.entries(args);
  if (entries.length === 0) {
    sEl.argsPills.innerHTML = '<span style="font-size: 11px; color: var(--s-muted);">No arguments</span>';
    return;
  }

  entries.forEach(([k, v]) => {
    const p = provMap[k];
    const trust = p?.trust || 'unknown';
    const pill = document.createElement('div');
    pill.className = 'arg-pill';
    pill.innerHTML = `
      <strong>${escapeHtml(k)}:</strong>
      <span>${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}</span>
      <small style="color: ${trust === 'trusted' ? 'var(--s-green)' : (trust === 'unknown' ? 'var(--s-muted)' : 'var(--s-rose)')}; font-size: 10px; font-weight: 700;">[${trust}]</small>
    `;
    sEl.argsPills.appendChild(pill);
  });
}

function renderPolicies(clauses) {
  sEl.policyList.innerHTML = '';
  if (!clauses || clauses.length === 0) {
    sEl.policyList.innerHTML = '<div style="color: var(--s-muted); font-size: 11px;">No policy clauses retrieved.</div>';
    return;
  }

  clauses.forEach((c) => {
    const isCited = sState.citedClauses.has(c.id);
    const item = document.createElement('div');
    item.className = `s-pol-item ${isCited ? 'cited' : ''}`;
    item.setAttribute('data-id', c.id);
    item.innerHTML = `
      <div class="s-pol-header">
        <span class="s-pol-id">${escapeHtml(c.id)}</span>
        <span class="s-pol-name">${escapeHtml(c.title)}</span>
        <button type="button" class="s-cite-btn">${isCited ? '✓ Cited' : '+ Cite'}</button>
      </div>
      <div class="s-pol-body">${escapeHtml(c.text)}</div>
    `;

    item.addEventListener('click', () => toggleCite(c.id));
    sEl.policyList.appendChild(item);
  });
}

function toggleCite(clauseId) {
  if (sState.citedClauses.has(clauseId)) {
    sState.citedClauses.delete(clauseId);
  } else {
    sState.citedClauses.add(clauseId);
  }
  renderCitedTags();
  document.querySelectorAll(`.s-pol-item[data-id="${clauseId}"]`).forEach((item) => {
    const isCited = sState.citedClauses.has(clauseId);
    item.classList.toggle('cited', isCited);
    item.querySelector('.s-cite-btn').textContent = isCited ? '✓ Cited' : '+ Cite';
  });
  sState.dirty = true;
}

function renderCitedTags() {
  sEl.citedTags.innerHTML = '';
  if (sState.citedClauses.size === 0) {
    sEl.citedTags.textContent = 'None';
    return;
  }

  sState.citedClauses.forEach((cid) => {
    const tag = document.createElement('span');
    tag.className = 's-tag-cited';
    tag.textContent = cid;
    sEl.citedTags.appendChild(tag);
  });
}

function populateForm() {
  const currentCase = sState.cases[sState.currentIndex];
  const label = sState.annotations[currentCase.case_id] || currentCase.current_label || {};

  sState.citedClauses.clear();
  if (label.gold_clause_ids) {
    const list = Array.isArray(label.gold_clause_ids)
      ? label.gold_clause_ids
      : String(label.gold_clause_ids).split(/[,;]/);
    list.forEach((cid) => { if (cid.trim()) sState.citedClauses.add(cid.trim()); });
  }
  renderCitedTags();

  setDecision(label.gold_decision || null, false);

  if (label.gold_missing_evidence) {
    sEl.missingPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_missing_evidence));
  }
  if (label.gold_required_authority) {
    sEl.authPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_required_authority));
  }

  sState.dirty = false;
}

function setDecision(decision, markDirty = true) {
  sEl.hudBtns.forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-decision') === decision);
  });

  sEl.askDrawer.style.display = decision === 'ASK_USER' ? 'flex' : 'none';
  sEl.escalateDrawer.style.display = decision === 'ESCALATE' ? 'flex' : 'none';

  sEl.statusIndicator.className = 'decision-badge';
  if (decision) {
    sEl.statusIndicator.textContent = decision;
    sEl.statusIndicator.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
  } else {
    sEl.statusIndicator.textContent = 'UNLABELED';
  }

  if (markDirty) {
    sState.dirty = true;
    sEl.saveStatus.textContent = 'Unsaved';
  }
}

function getDecision() {
  const active = document.querySelector('.hud-btn.active');
  return active ? active.getAttribute('data-decision') : null;
}

async function saveCurrent() {
  const currentCase = sState.cases[sState.currentIndex];
  if (!currentCase) return;

  const decision = getDecision();
  if (!decision) return;

  const activeMissing = document.querySelector('#sMissingPills .sub-pill.active');
  const activeAuth = document.querySelector('#sAuthPills .sub-pill.active');

  const labelData = {
    case_id: currentCase.case_id,
    gold_decision: decision,
    gold_final_action: (decision === 'ALLOW' || decision === 'BLOCK') ? decision : 'ALLOW',
    gold_missing_evidence: decision === 'ASK_USER' ? (activeMissing ? activeMissing.getAttribute('data-val') : 'user_intent') : '',
    gold_required_authority: decision === 'ESCALATE' ? (activeAuth ? activeAuth.getAttribute('data-val') : 'manager') : '',
    gold_clause_ids: Array.from(sState.citedClauses).join(', '),
    user_response_text: '',
    user_response_confirmed: 'yes',
    notes: '',
  };

  sState.annotations[currentCase.case_id] = labelData;
  currentCase.current_label = labelData;

  try {
    await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_id: sState.currentBatchId,
        annotator: sState.annotator,
        case_id: currentCase.case_id,
        label: labelData,
      }),
    });
    sEl.saveStatus.textContent = 'Saved';
  } catch {
    sEl.saveStatus.textContent = 'Offline';
  }

  sState.dirty = false;
  updateProgress();
  renderQueue();
}

async function saveAndNext() {
  await saveCurrent();
  if (sState.currentIndex < sState.cases.length - 1) {
    jump(sState.currentIndex + 1);
  } else {
    alert('🎉 Batch complete!');
  }
}

function jump(idx) {
  if (idx < 0 || idx >= sState.cases.length) return;
  if (sState.dirty) saveCurrent();
  sState.currentIndex = idx;
  renderCase();
}

function nextUnlabeled() {
  if (sState.dirty) saveCurrent();
  for (let i = sState.currentIndex + 1; i < sState.cases.length; i++) {
    if (!sState.annotations[sState.cases[i].case_id]?.gold_decision) {
      jump(i);
      return;
    }
  }
  for (let i = 0; i <= sState.currentIndex; i++) {
    if (!sState.annotations[sState.cases[i].case_id]?.gold_decision) {
      jump(i);
      return;
    }
  }
  alert('All cases labeled in this batch!');
}

function updateProgress() {
  const total = sState.cases.length || 100;
  const labeled = Object.values(sState.annotations).filter((a) => a.gold_decision).length;
  sEl.progressBadge.textContent = `${labeled}/${total}`;
}

function setupEvents() {
  sEl.annotatorSelect.addEventListener('change', () => {
    sState.annotator = sEl.annotatorSelect.value;
    localStorage.setItem('sagate_annotator', sState.annotator);
    loadManifest();
    loadBatch(sState.currentBatchId);
  });

  sEl.batchSelect.addEventListener('change', () => {
    if (sState.dirty) saveCurrent();
    loadBatch(sEl.batchSelect.value);
  });

  sEl.saveNextBtn.addEventListener('click', saveAndNext);
  sEl.btnNextUnlabeled.addEventListener('click', nextUnlabeled);

  sEl.btnExport.addEventListener('click', () => {
    if (sState.dirty) saveCurrent();
    window.open(`/api/export?batch_id=${sState.currentBatchId}&annotator=${sState.annotator}`, '_blank');
  });

  sEl.hudBtns.forEach((btn) => {
    btn.addEventListener('click', () => setDecision(btn.getAttribute('data-decision')));
  });

  sEl.missingPills.forEach((p) => {
    p.addEventListener('click', () => {
      sEl.missingPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      sState.dirty = true;
    });
  });

  sEl.authPills.forEach((p) => {
    p.addEventListener('click', () => {
      sEl.authPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      sState.dirty = true;
    });
  });

  window.addEventListener('keydown', (e) => {
    const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (isInput) return;

    switch (e.key) {
      case '1': e.preventDefault(); setDecision('ALLOW'); break;
      case '2': e.preventDefault(); setDecision('BLOCK'); break;
      case '3': e.preventDefault(); setDecision('ASK_USER'); break;
      case '4': e.preventDefault(); setDecision('ESCALATE'); break;
      case 'Enter': e.preventDefault(); saveAndNext(); break;
      case '[':
      case 'ArrowUp':
      case 'ArrowLeft': e.preventDefault(); jump(sState.currentIndex - 1); break;
      case ']':
      case 'ArrowDown':
      case 'ArrowRight': e.preventDefault(); jump(sState.currentIndex + 1); break;
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

window.addEventListener('DOMContentLoaded', sInit);
