/**
 * SaGate Zen Minimalist Client
 */

const zenState = {
  annotator: 'rinkesh',
  currentBatchId: 'batch_01',
  manifest: null,
  cases: [],
  currentIndex: 0,
  annotations: {},
  citedClauses: new Set(),
  dirty: false,
};

const zenEl = {
  annotatorSelect: document.getElementById('zenAnnotatorSelect'),
  batchSelect: document.getElementById('zenBatchSelect'),
  progressText: document.getElementById('zenProgressText'),
  progressFill: document.getElementById('zenProgressFill'),
  btnUnlabeled: document.getElementById('zenBtnUnlabeled'),
  btnExport: document.getElementById('zenBtnExport'),
  btnHelp: document.getElementById('zenBtnHelp'),
  prevBtn: document.getElementById('zenPrevBtn'),
  nextBtn: document.getElementById('zenNextBtn'),
  caseIdx: document.getElementById('zenCaseIdx'),
  badgeSuite: document.getElementById('badgeSuite'),
  badgeCategory: document.getElementById('badgeCategory'),
  badgeDifficulty: document.getElementById('badgeDifficulty'),
  badgeStatus: document.getElementById('badgeStatus'),
  principal: document.getElementById('zenPrincipal'),
  promptText: document.getElementById('zenPromptText'),
  fnName: document.getElementById('zenFnName'),
  stateBadge: document.getElementById('zenStateBadge'),
  argsList: document.getElementById('zenArgsList'),
  authorityVal: document.getElementById('zenAuthorityVal'),
  flowVal: document.getElementById('zenFlowVal'),
  approverVal: document.getElementById('zenApproverVal'),
  untrustedSec: document.getElementById('zenUntrustedSec'),
  untrustedContent: document.getElementById('zenUntrustedContent'),
  policiesGrid: document.getElementById('zenPoliciesGrid'),
  saveStatus: document.getElementById('zenSaveStatus'),
  decisionBtns: document.querySelectorAll('.zen-decision-btn'),
  askExtension: document.getElementById('zenAskExtension'),
  escalateExtension: document.getElementById('zenEscalateExtension'),
  missingPills: document.querySelectorAll('#zenMissingPills .zen-pill'),
  authPills: document.querySelectorAll('#zenAuthPills .zen-pill'),
  userReplyInput: document.getElementById('zenUserReplyInput'),
  replyYes: document.getElementById('zenReplyYes'),
  replyNo: document.getElementById('zenReplyNo'),
  citedTags: document.getElementById('zenCitedTags'),
  notesInput: document.getElementById('zenNotesInput'),
  saveBtn: document.getElementById('zenSaveBtn'),
  modal: document.getElementById('zenModal'),
  closeModal: document.getElementById('zenCloseModal'),
};

async function zenInit() {
  const saved = localStorage.getItem('sagate_annotator');
  if (saved) {
    zenState.annotator = saved;
    zenEl.annotatorSelect.value = saved;
  }

  setupZenEvents();
  await zenLoadManifest();
  await zenLoadBatch(zenState.currentBatchId);
}

async function zenLoadManifest() {
  try {
    const res = await fetch(`/api/manifest?annotator=${encodeURIComponent(zenState.annotator)}`);
    zenState.manifest = await res.json();
    zenEl.batchSelect.innerHTML = '';
    (zenState.manifest.batches || []).forEach((b) => {
      const opt = document.createElement('option');
      opt.value = b.batch_id;
      opt.textContent = `Batch ${b.batch_num.toString().padStart(2, '0')} (${b.labeled_count || 0}/${b.case_count})`;
      zenEl.batchSelect.appendChild(opt);
    });
    zenEl.batchSelect.value = zenState.currentBatchId;
  } catch (err) {
    console.error('Error loading manifest:', err);
  }
}

async function zenLoadBatch(batchId) {
  zenState.currentBatchId = batchId;
  zenEl.saveStatus.textContent = 'Loading...';

  try {
    const res = await fetch(`/api/batch?id=${batchId}&annotator=${encodeURIComponent(zenState.annotator)}`);
    const data = await res.json();
    zenState.cases = data.cases || [];
    zenState.annotations = data.annotations || {};
  } catch (err) {
    console.error('Error loading batch:', err);
    return;
  }

  zenState.currentIndex = 0;
  zenUpdateProgress();
  zenRenderCase();
  zenEl.saveStatus.textContent = 'Saved';
}

function zenRenderCase() {
  if (!zenState.cases || zenState.cases.length === 0) return;

  const item = zenState.cases[zenState.currentIndex];
  const raw = item.raw_case || {};
  const inp = raw.input || {};
  const meta = item.raw_case?.meta || {};

  zenEl.caseIdx.textContent = zenState.currentIndex + 1;
  zenEl.badgeSuite.textContent = item.suite || 'banking';
  zenEl.badgeCategory.textContent = item.category || 'general';
  zenEl.badgeDifficulty.textContent = item.difficulty || 'medium';

  // Prompt
  zenEl.principal.textContent = inp.user?.principal_id || 'user';
  zenEl.promptText.textContent = inp.user?.prompt || '(No prompt)';

  // Action
  const call = inp.proposed_call || {};
  zenEl.fnName.textContent = `${call.function || 'unknown_tool'}()`;
  zenEl.stateBadge.style.display = call.state_changing ? 'inline-block' : 'none';

  // Args
  zenRenderArgs(call.args || {}, inp.provenance || []);

  // Security Context
  const auth = inp.authority || {};
  const sens = inp.sensitivity || {};
  zenEl.authorityVal.textContent = `${auth.principal || 'user'} (${auth.principal_role || 'role'}) — ${auth.user_may_authorize ? 'Authorized' : 'Unauthorized'}`;
  zenEl.flowVal.textContent = `${sens.resource || 'PUBLIC'} → ${sens.destination || 'INTERNAL'} [${(sens.flow || 'ok').toUpperCase()}]`;
  zenEl.approverVal.textContent = auth.approver || 'None required';

  // Untrusted context
  const untrusted = inp.untrusted_content || [];
  if (untrusted.length > 0) {
    zenEl.untrustedSec.style.display = 'flex';
    zenEl.untrustedContent.textContent = untrusted.map((u) => `[${u.id} - ${u.source}]\n${u.text}`).join('\n\n');
  } else {
    zenEl.untrustedSec.style.display = 'none';
  }

  // Policies
  zenRenderPolicies(inp.policy_clauses || []);

  // Populate decision
  zenPopulateForm();
}

function zenRenderArgs(args, provenance) {
  zenEl.argsList.innerHTML = '';
  const provMap = {};
  provenance.forEach((p) => { if (p.arg) provMap[p.arg] = p; });

  const entries = Object.entries(args);
  if (entries.length === 0) {
    zenEl.argsList.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); font-style: italic;">No arguments</div>';
    return;
  }

  entries.forEach(([key, val]) => {
    const p = provMap[key];
    const trust = p?.trust || 'unknown';
    const tagClass = trust === 'trusted' ? 'trust-trusted' : (trust === 'unknown' ? 'trust-unknown' : 'trust-untrusted');

    const row = document.createElement('div');
    row.className = 'arg-row';
    row.innerHTML = `
      <span class="arg-key">${escapeHtml(key)}:</span>
      <div class="arg-val-box">
        <span class="arg-value">${escapeHtml(typeof val === 'object' ? JSON.stringify(val) : String(val))}</span>
        <span class="arg-trust-tag ${tagClass}">${trust}</span>
      </div>
    `;
    zenEl.argsList.appendChild(row);
  });
}

function zenRenderPolicies(clauses) {
  zenEl.policiesGrid.innerHTML = '';
  if (!clauses || clauses.length === 0) {
    zenEl.policiesGrid.innerHTML = '<div style="font-size: 12px; color: var(--text-muted);">No policies retrieved.</div>';
    return;
  }

  clauses.forEach((c) => {
    const isCited = zenState.citedClauses.has(c.id);
    const card = document.createElement('div');
    card.className = `zen-policy-card ${isCited ? 'cited' : ''}`;
    card.setAttribute('data-id', c.id);
    card.innerHTML = `
      <div class="policy-head">
        <span class="policy-id-badge">${escapeHtml(c.id)}</span>
        <span class="policy-title-text">${escapeHtml(c.title)}</span>
        <button type="button" class="zen-cite-btn">${isCited ? '✓ Cited' : '+ Cite'}</button>
      </div>
      <div class="policy-body-text">${escapeHtml(c.text)}</div>
    `;

    card.querySelector('.zen-cite-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      zenToggleCiteClause(c.id);
    });

    zenEl.policiesGrid.appendChild(card);
  });
}

function zenToggleCiteClause(clauseId) {
  if (zenState.citedClauses.has(clauseId)) {
    zenState.citedClauses.delete(clauseId);
  } else {
    zenState.citedClauses.add(clauseId);
  }
  zenRenderCitedTags();
  // Update card UI
  document.querySelectorAll(`.zen-policy-card[data-id="${clauseId}"]`).forEach((card) => {
    const isCited = zenState.citedClauses.has(clauseId);
    card.classList.toggle('cited', isCited);
    card.querySelector('.zen-cite-btn').textContent = isCited ? '✓ Cited' : '+ Cite';
  });
  zenState.dirty = true;
}

function zenRenderCitedTags() {
  zenEl.citedTags.innerHTML = '';
  if (zenState.citedClauses.size === 0) {
    zenEl.citedTags.innerHTML = '<span class="empty-hint">None cited yet (click "+ Cite" on policies above)</span>';
    return;
  }

  zenState.citedClauses.forEach((cid) => {
    const badge = document.createElement('span');
    badge.className = 'tag-badge';
    badge.innerHTML = `${escapeHtml(cid)} <span data-id="${escapeHtml(cid)}">&times;</span>`;
    badge.querySelector('span').addEventListener('click', () => {
      zenToggleCiteClause(cid);
    });
    zenEl.citedTags.appendChild(badge);
  });
}

function zenPopulateForm() {
  const currentCase = zenState.cases[zenState.currentIndex];
  const label = zenState.annotations[currentCase.case_id] || currentCase.current_label || {};

  zenState.citedClauses.clear();
  if (label.gold_clause_ids) {
    const list = Array.isArray(label.gold_clause_ids)
      ? label.gold_clause_ids
      : String(label.gold_clause_ids).split(/[,;]/);
    list.forEach((cid) => { if (cid.trim()) zenState.citedClauses.add(cid.trim()); });
  }
  zenRenderCitedTags();

  zenSetDecision(label.gold_decision || null, false);

  if (label.gold_missing_evidence) {
    zenEl.missingPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_missing_evidence));
  }
  if (label.gold_required_authority) {
    zenEl.authPills.forEach((p) => p.classList.toggle('active', p.getAttribute('data-val') === label.gold_required_authority));
  }

  zenEl.userReplyInput.value = label.user_response_text || '';
  const conf = label.user_response_confirmed;
  zenEl.replyYes.classList.toggle('active', conf === 'yes' || conf === true);
  zenEl.replyNo.classList.toggle('active', conf === 'no' || conf === false);

  zenEl.notesInput.value = label.notes || '';
  zenState.dirty = false;
}

function zenSetDecision(decision, markDirty = true) {
  zenEl.decisionBtns.forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-decision') === decision);
  });

  zenEl.askExtension.style.display = decision === 'ASK_USER' ? 'flex' : 'none';
  zenEl.escalateExtension.style.display = decision === 'ESCALATE' ? 'flex' : 'none';

  zenEl.badgeStatus.className = 'zen-chip status-chip';
  if (decision) {
    zenEl.badgeStatus.textContent = decision;
    zenEl.badgeStatus.classList.add(`labeled-${decision.toLowerCase().replace('_', '')}`);
  } else {
    zenEl.badgeStatus.textContent = 'UNLABELED';
  }

  if (markDirty) {
    zenState.dirty = true;
    zenEl.saveStatus.textContent = 'Unsaved changes';
  }
}

function zenGetDecision() {
  const active = document.querySelector('.zen-decision-btn.active');
  return active ? active.getAttribute('data-decision') : null;
}

async function zenSave() {
  const currentCase = zenState.cases[zenState.currentIndex];
  if (!currentCase) return;

  const decision = zenGetDecision();
  if (!decision) return;

  const activeMissing = document.querySelector('#zenMissingPills .zen-pill.active');
  const activeAuth = document.querySelector('#zenAuthPills .zen-pill.active');

  const labelData = {
    case_id: currentCase.case_id,
    gold_decision: decision,
    gold_final_action: (decision === 'ALLOW' || decision === 'BLOCK') ? decision : 'ALLOW',
    gold_missing_evidence: decision === 'ASK_USER' ? (activeMissing ? activeMissing.getAttribute('data-val') : 'user_intent') : '',
    gold_required_authority: decision === 'ESCALATE' ? (activeAuth ? activeAuth.getAttribute('data-val') : 'manager') : '',
    gold_clause_ids: Array.from(zenState.citedClauses).join(', '),
    user_response_text: zenEl.userReplyInput.value.trim(),
    user_response_confirmed: zenEl.replyYes.classList.contains('active') ? 'yes' : (zenEl.replyNo.classList.contains('active') ? 'no' : ''),
    notes: zenEl.notesInput.value.trim(),
  };

  zenState.annotations[currentCase.case_id] = labelData;
  currentCase.current_label = labelData;

  try {
    await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_id: zenState.currentBatchId,
        annotator: zenState.annotator,
        case_id: currentCase.case_id,
        label: labelData,
      }),
    });
    zenEl.saveStatus.textContent = 'Saved to disk';
  } catch {
    zenEl.saveStatus.textContent = 'Saved locally';
  }

  zenState.dirty = false;
  zenUpdateProgress();
}

async function zenSaveAndNext() {
  await zenSave();
  if (zenState.currentIndex < zenState.cases.length - 1) {
    zenJump(zenState.currentIndex + 1);
  } else {
    alert('🎉 Batch complete!');
  }
}

function zenJump(idx) {
  if (idx < 0 || idx >= zenState.cases.length) return;
  if (zenState.dirty) zenSave();
  zenState.currentIndex = idx;
  zenRenderCase();
}

function zenNextUnlabeled() {
  if (zenState.dirty) zenSave();
  for (let i = zenState.currentIndex + 1; i < zenState.cases.length; i++) {
    if (!zenState.annotations[zenState.cases[i].case_id]?.gold_decision) {
      zenJump(i);
      return;
    }
  }
  for (let i = 0; i <= zenState.currentIndex; i++) {
    if (!zenState.annotations[zenState.cases[i].case_id]?.gold_decision) {
      zenJump(i);
      return;
    }
  }
  alert('All cases labeled in this batch!');
}

function zenUpdateProgress() {
  const total = zenState.cases.length || 100;
  const labeled = Object.values(zenState.annotations).filter((a) => a.gold_decision).length;
  const pct = Math.round((labeled / total) * 100);

  zenEl.progressText.textContent = `${labeled} / ${total} (${pct}%)`;
  zenEl.progressFill.style.width = `${pct}%`;
}

function setupZenEvents() {
  zenEl.annotatorSelect.addEventListener('change', () => {
    zenState.annotator = zenEl.annotatorSelect.value;
    localStorage.setItem('sagate_annotator', zenState.annotator);
    zenLoadManifest();
    zenLoadBatch(zenState.currentBatchId);
  });

  zenEl.batchSelect.addEventListener('change', () => {
    if (zenState.dirty) zenSave();
    zenLoadBatch(zenEl.batchSelect.value);
  });

  zenEl.prevBtn.addEventListener('click', () => zenJump(zenState.currentIndex - 1));
  zenEl.nextBtn.addEventListener('click', () => zenJump(zenState.currentIndex + 1));
  zenEl.saveBtn.addEventListener('click', zenSaveAndNext);
  zenEl.btnUnlabeled.addEventListener('click', zenNextUnlabeled);

  zenEl.btnExport.addEventListener('click', () => {
    if (zenState.dirty) zenSave();
    window.open(`/api/export?batch_id=${zenState.currentBatchId}&annotator=${zenState.annotator}`, '_blank');
  });

  zenEl.decisionBtns.forEach((btn) => {
    btn.addEventListener('click', () => zenSetDecision(btn.getAttribute('data-decision')));
  });

  zenEl.missingPills.forEach((p) => {
    p.addEventListener('click', () => {
      zenEl.missingPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      zenState.dirty = true;
    });
  });

  zenEl.authPills.forEach((p) => {
    p.addEventListener('click', () => {
      zenEl.authPills.forEach((x) => x.classList.remove('active'));
      p.classList.add('active');
      zenState.dirty = true;
    });
  });

  zenEl.replyYes.addEventListener('click', () => {
    zenEl.replyYes.classList.add('active');
    zenEl.replyNo.classList.remove('active');
    zenState.dirty = true;
  });
  zenEl.replyNo.addEventListener('click', () => {
    zenEl.replyNo.classList.add('active');
    zenEl.replyYes.classList.remove('active');
    zenState.dirty = true;
  });

  zenEl.btnHelp.addEventListener('click', () => zenEl.modal.classList.add('active'));
  zenEl.closeModal.addEventListener('click', () => zenEl.modal.classList.remove('active'));
  zenEl.modal.addEventListener('click', (e) => {
    if (e.target === zenEl.modal) zenEl.modal.classList.remove('active');
  });

  window.addEventListener('keydown', (e) => {
    const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (isInput) {
      if (e.key === 'Enter' && e.ctrlKey) {
        e.preventDefault();
        zenSaveAndNext();
      }
      return;
    }

    switch (e.key) {
      case '1': e.preventDefault(); zenSetDecision('ALLOW'); break;
      case '2': e.preventDefault(); zenSetDecision('BLOCK'); break;
      case '3': e.preventDefault(); zenSetDecision('ASK_USER'); break;
      case '4': e.preventDefault(); zenSetDecision('ESCALATE'); break;
      case 'Enter': e.preventDefault(); zenSaveAndNext(); break;
      case '[':
      case 'ArrowLeft': e.preventDefault(); zenJump(zenState.currentIndex - 1); break;
      case ']':
      case 'ArrowRight': e.preventDefault(); zenJump(zenState.currentIndex + 1); break;
      case 'u':
      case 'U': e.preventDefault(); zenNextUnlabeled(); break;
      case '?': e.preventDefault(); zenEl.modal.classList.toggle('active'); break;
      case 'Escape': zenEl.modal.classList.remove('active'); break;
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

window.addEventListener('DOMContentLoaded', zenInit);
