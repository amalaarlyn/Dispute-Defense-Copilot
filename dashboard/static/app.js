/**
 * Dispute Defense Copilot — Dashboard v2
 * 
 * Features:
 * - Pipeline step animations (stage-by-stage activation)
 * - AI investigation findings with slide-in effects
 * - Human brief panel for escalated cases
 * - Human feedback modal with override capture
 * - Agent metrics live tracking in bottom ribbon
 * - Smooth animated gauge and counters
 * - Search with debounce
 */

(function () {
  'use strict';

  const API = '';

  // DOM
  const disputeListEl = document.getElementById('dispute-list');
  const searchInput = document.getElementById('search-input');
  const analysisView = document.getElementById('analysis-view');
  const emptyState = document.getElementById('empty-state');
  const feedbackModal = document.getElementById('feedback-modal');

  let allDisputes = [];
  let activeId = null;
  let currentAnalysis = null;

  // =========================================================================
  // Disputes List
  // =========================================================================

  async function loadDisputes() {
    try {
      const res = await fetch(`${API}/api/disputes`);
      allDisputes = await res.json();
      renderDisputeList(allDisputes);
    } catch (err) {
      disputeListEl.innerHTML = '<div class="loading">Failed to load disputes.</div>';
    }
  }

  function renderDisputeList(disputes) {
    if (!disputes.length) {
      disputeListEl.innerHTML = '<div class="loading">No disputes found.</div>';
      return;
    }

    disputeListEl.innerHTML = disputes.map(d => {
      const shortId = d.dispute_id.replace('disp_', '').substring(0, 10);
      return `
        <div class="dispute-item ${d.dispute_id === activeId ? 'active' : ''}" data-id="${d.dispute_id}">
          <div class="item-id">disp_${shortId}…</div>
          <div class="item-row">
            <span class="item-amount">₹${Number(d.amount).toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
            <span class="item-badge ${d.has_tamper ? 'tamper' : ''}">${d.has_tamper ? '⚠ Tamper' : fmtReason(d.reason_code)}</span>
          </div>
        </div>
      `;
    }).join('');

    disputeListEl.querySelectorAll('.dispute-item').forEach(el => {
      el.addEventListener('click', () => selectDispute(el.dataset.id));
    });
  }

  function fmtReason(code) {
    if (!code) return '—';
    return code.replace(/_/g, ' ').split(' ').map(w => w[0]?.toUpperCase() + w.slice(1)).join(' ');
  }

  // Search with debounce
  let searchTimeout;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      const q = searchInput.value.toLowerCase().trim();
      if (!q) { renderDisputeList(allDisputes); return; }
      const filtered = allDisputes.filter(d =>
        d.dispute_id.toLowerCase().includes(q) ||
        (d.reason_code || '').toLowerCase().includes(q)
      );
      renderDisputeList(filtered);
    }, 200);
  });

  // =========================================================================
  // Select & Analyze
  // =========================================================================

  async function selectDispute(disputeId) {
    activeId = disputeId;

    disputeListEl.querySelectorAll('.dispute-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === disputeId);
    });

    emptyState.classList.add('hidden');
    analysisView.classList.remove('hidden');
    analysisView.innerHTML = renderSkeleton();

    // Update agent status
    setAgentStatus('investigating');

    try {
      const res = await fetch(`${API}/api/disputes/${disputeId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      currentAnalysis = data;
      renderAnalysis(data);
      setAgentStatus('online');
      updateMetrics();
    } catch (err) {
      analysisView.innerHTML = `<div class="loading" style="color: var(--neon-rose);">Analysis failed: ${err.message}</div>`;
      setAgentStatus('online');
    }
  }

  function setAgentStatus(status) {
    const dot = document.getElementById('agent-status-dot');
    const text = document.getElementById('agent-status-text');
    if (status === 'investigating') {
      dot.className = 'status-dot investigating';
      text.textContent = 'Agent Investigating…';
    } else {
      dot.className = 'status-dot online';
      text.textContent = 'Agent Online';
    }
  }

  function renderSkeleton() {
    return `
      <div class="skeleton skeleton-block" style="height:140px;border-radius:20px;"></div>
      <div class="skeleton skeleton-block" style="height:60px;border-radius:20px;"></div>
      <div class="grid-2">
        <div class="skeleton skeleton-block" style="height:200px;border-radius:16px;"></div>
        <div class="skeleton skeleton-block" style="height:200px;border-radius:16px;"></div>
      </div>
    `;
  }

  // =========================================================================
  // Render Full Analysis
  // =========================================================================

  function renderAnalysis(data) {
    const decision = data.decision?.decision || 'human_review';
    const investigation = data.investigation;
    const hasAgent = !!investigation;
    const agentResolved = investigation?.status === 'resolved';
    const humanBrief = data.decision?.human_brief || investigation?.human_brief;

    // Calculate amount from features
    const amountLog = data.features?.amount_log || 0;
    const amount = Math.expm1(amountLog);
    const hoursRemaining = data.features?.hours_remaining || 0;

    analysisView.innerHTML = `
      ${renderHero(data, amount, hoursRemaining)}
      ${renderPipeline(data.pipeline_stages || [])}
      <div class="grid-2">
        <div>
          ${renderRecommendation(data, decision, hasAgent, agentResolved)}
          ${renderGauge(data.win_probability)}
          ${hasAgent ? renderInvestigation(investigation) : ''}
          ${humanBrief ? renderHumanBrief(humanBrief) : ''}
        </div>
        <div>
          ${renderEvidence(data.verifier_results)}
          ${renderWhatIf(data.whatif_results)}
        </div>
      </div>
    `;

    // Animate gauge
    requestAnimationFrame(() => animateGauge(data.win_probability));

    // Animate pipeline steps
    animatePipeline(data.pipeline_stages || []);
  }

  // =========================================================================
  // Hero Card
  // =========================================================================

  function renderHero(data, amount, hoursRemaining) {
    const validCount = (data.verifier_results || []).filter(r => r.predicted_valid).length;
    const totalCount = (data.verifier_results || []).length;

    return `
      <div class="hero-card">
        <div class="hero-top">
          <div class="hero-id">${data.dispute_id}</div>
          <span class="hero-reason">${fmtReason(data.reason_code)}</span>
        </div>
        <div class="hero-stats">
          <div class="hero-stat">
            <span class="hero-stat-label">Dispute Amount</span>
            <span class="hero-stat-value amount">₹${amount.toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Time Remaining</span>
            <span class="hero-stat-value time">${hoursRemaining.toFixed(0)}h</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Win Probability</span>
            <span class="hero-stat-value probability">${(data.win_probability * 100).toFixed(1)}%</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Evidence</span>
            <span class="hero-stat-value evidence">${validCount}/${totalCount} valid</span>
          </div>
        </div>
      </div>
    `;
  }

  // =========================================================================
  // Pipeline Steps
  // =========================================================================

  function renderPipeline(stages) {
    if (!stages.length) return '';

    const stepsHtml = stages.map((s, i) => {
      const connector = i < stages.length - 1
        ? `<div class="pipeline-connector" data-step="${i}"></div>`
        : '';
      return `
        <div class="pipeline-step" data-step="${i}">
          <div class="step-icon">${s.icon}</div>
          <div>
            <div class="step-name">${s.name}</div>
            <div class="step-summary">${s.summary}</div>
          </div>
        </div>
        ${connector}
      `;
    }).join('');

    return `
      <div class="pipeline-card">
        <div class="pipeline-label">Pipeline Execution</div>
        <div class="pipeline-steps">${stepsHtml}</div>
      </div>
    `;
  }

  function animatePipeline(stages) {
    const steps = document.querySelectorAll('.pipeline-step');
    const connectors = document.querySelectorAll('.pipeline-connector');

    steps.forEach((step, i) => {
      setTimeout(() => {
        step.classList.add('completed');
        if (connectors[i]) connectors[i].classList.add('completed');
      }, 200 + i * 250);
    });
  }

  // =========================================================================
  // Recommendation Card
  // =========================================================================

  function renderRecommendation(data, decision, hasAgent, agentResolved) {
    const labels = {
      'recommend_contest': '✅ Contest Dispute',
      'recommend_accept': '❌ Accept Chargeback',
      'human_review': '👤 Human Review Required',
      'recommend_obtain_evidence': '📋 Gather More Evidence',
      'agent_investigation': '🤖 Agent Investigating',
    };

    const agentTag = hasAgent
      ? agentResolved
        ? '<span class="agent-badge">🤖 Resolved by AI Agent</span>'
        : '<span class="agent-badge">🤖 Investigated by AI Agent</span>'
      : '';

    const overrideBtn = `<button class="btn btn-override" onclick="window._openFeedback()">✏️ Override Decision</button>`;

    return `
      <div class="card recommendation-card ${decision}">
        <div class="card-title"><span class="title-icon">⚖️</span> Recommendation</div>
        <div class="action-badge ${decision}">${labels[decision] || decision}</div>
        <p class="narrative">${data.narrative || data.decision?.reason || ''}</p>
        ${agentTag}
        <div style="margin-top:14px;">${overrideBtn}</div>
      </div>
    `;
  }

  // =========================================================================
  // Gauge
  // =========================================================================

  function renderGauge(winProb) {
    return `
      <div class="card" style="text-align:center;">
        <div class="card-title" style="justify-content:center;"><span class="title-icon">📊</span> Win Probability</div>
        <div class="gauge-container">
          <svg viewBox="0 0 100 55" class="gauge">
            <defs>
              <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color: #fb7185"/>
                <stop offset="50%" style="stop-color: #fbbf24"/>
                <stop offset="100%" style="stop-color: #34d399"/>
              </linearGradient>
            </defs>
            <path class="gauge-bg" d="M 10 50 A 40 40 0 0 1 90 50" />
            <path class="gauge-value" id="gauge-path" d="M 10 50 A 40 40 0 0 1 90 50"
                  stroke="url(#gaugeGrad)"
                  stroke-dasharray="125.66"
                  stroke-dashoffset="125.66" />
          </svg>
          <div class="gauge-text" id="gauge-text">0%</div>
        </div>
      </div>
    `;
  }

  function animateGauge(winProb) {
    const path = document.getElementById('gauge-path');
    const text = document.getElementById('gauge-text');
    if (!path || !text) return;

    const totalLength = 125.66;
    const offset = totalLength * (1 - winProb);

    setTimeout(() => {
      path.style.strokeDashoffset = offset;
      animateCounter(text, 0, winProb * 100, 1000);
    }, 300);
  }

  function animateCounter(el, start, end, duration) {
    const startTime = performance.now();
    function update(t) {
      const elapsed = t - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = `${(start + (end - start) * eased).toFixed(1)}%`;
      if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  }

  // =========================================================================
  // AI Investigation Panel
  // =========================================================================

  function renderInvestigation(inv) {
    if (!inv) return '';

    const status = inv.status === 'resolved' ? 'resolved' : 'escalated';
    const statusLabel = status === 'resolved' ? 'Resolved' : 'Escalated to Human';
    const steps = inv.investigation_steps || [];
    const findings = inv.findings_summary || [];

    const toolIcons = {
      'check_document_consistency': '📄',
      'analyze_tamper_signal': '🔍',
      'calculate_cost_tradeoff': '💰',
      'get_deadline_urgency': '⏰',
      'search_similar_cases': '🔎',
      'get_deadline_urgency + calculate_cost_tradeoff': '⏰💰',
      'check_document_consistency + search_similar_cases': '📄🔎',
    };

    const stepsHtml = steps.map(s => `
      <div class="inv-step">
        <div class="inv-step-icon">${toolIcons[s.tool] || '🔧'}</div>
        <div class="inv-step-content">
          <div class="inv-step-title">${s.description}</div>
          <div class="inv-step-result">${s.conclusion}</div>
        </div>
      </div>
    `).join('');

    const findingsHtml = findings.length ? `
      <div class="findings-list">
        <div class="card-title"><span class="title-icon">💡</span> Key Findings</div>
        ${findings.map(f => `
          <div class="finding-item">
            <span class="finding-bullet">▸</span>
            <span>${f}</span>
          </div>
        `).join('')}
      </div>
    ` : '';

    // Uncertainty analysis
    const uncertainty = inv.uncertainty_analysis || {};
    const primaryType = uncertainty.primary_uncertainty || '';
    const overallSeverity = uncertainty.overall_severity || 0;

    return `
      <div class="card investigation-card">
        <div class="investigation-header">
          <div class="agent-icon">🤖</div>
          <h3>AI Case Investigation</h3>
          <span class="inv-status ${status}">${statusLabel}</span>
        </div>
        ${primaryType ? `
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:14px;">
            Primary uncertainty: <strong style="color:var(--neon-violet);">${primaryType.replace(/_/g, ' ')}</strong>
            · Severity: <strong style="color:${overallSeverity > 0.7 ? 'var(--neon-rose)' : overallSeverity > 0.4 ? 'var(--neon-amber)' : 'var(--neon-emerald)'};">${(overallSeverity * 100).toFixed(0)}%</strong>
          </div>
        ` : ''}
        <div class="investigation-steps">${stepsHtml}</div>
        ${findingsHtml}
      </div>
    `;
  }

  // =========================================================================
  // Human Brief
  // =========================================================================

  function renderHumanBrief(brief) {
    if (!brief) return '';

    const alreadyHtml = (brief.already_investigated || []).map(item => `
      <div class="brief-item">
        <strong>✅ ${item.check}</strong>
        ${item.result}
      </div>
    `).join('');

    const focusHtml = (brief.human_focus_areas || []).map(area => {
      const severity = area.severity || 0;
      const icon = severity > 0.7 ? '🔴' : severity > 0.4 ? '🟡' : '🟢';
      return `
        <div class="brief-item">
          <strong>${icon} ${(area.area || '').replace(/_/g, ' ')}</strong>
          ${area.description || ''}
          ${area.suggested_action ? `<div style="margin-top:4px;color:var(--neon-cyan);font-size:12px;">💡 ${area.suggested_action}</div>` : ''}
        </div>
      `;
    }).join('');

    return `
      <div class="card human-brief-card" style="position:relative;">
        <div class="card-title"><span class="title-icon">📋</span> AI Investigation Brief for Human</div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">${brief.summary || ''}</p>
        
        ${alreadyHtml ? `
          <div class="brief-section">
            <div class="brief-section-title">✅ Already Investigated by AI</div>
            ${alreadyHtml}
          </div>
        ` : ''}
        
        ${focusHtml ? `
          <div class="brief-section">
            <div class="brief-section-title">🎯 Human Should Investigate</div>
            ${focusHtml}
          </div>
        ` : ''}
        
        ${brief.time_saved_estimate ? `<div class="time-saved">⏱️ ${brief.time_saved_estimate}</div>` : ''}
      </div>
    `;
  }

  // =========================================================================
  // Evidence Verifier
  // =========================================================================

  function renderEvidence(results) {
    if (!results || !results.length) {
      return `<div class="card"><div class="card-title"><span class="title-icon">🔍</span> Evidence Verifier</div><p style="color:var(--text-dim);font-size:13px;">No evidence submitted.</p></div>`;
    }

    const itemsHtml = results.map(r => {
      const mismatches = (r.field_mismatches || []).map(m =>
        `<div class="ev-mismatch">⚠ ${m.field}: "${m.extracted}" vs "${m.expected}" (${(m.match_score * 100).toFixed(0)}%)</div>`
      ).join('');

      return `
        <div class="evidence-item">
          <div class="ev-status ${r.predicted_valid ? 'valid' : 'invalid'}"></div>
          <div class="ev-info">
            <div class="ev-type">${fmtReason(r.evidence_type)}</div>
            <div class="ev-detail">
              ${r.predicted_valid ? '✓ Valid' : '✗ Invalid'} · ${(r.confidence * 100).toFixed(1)}% confidence
              ${r.is_relevant ? '' : ' · <span style="color:var(--neon-amber)">Not Required</span>'}
            </div>
            ${mismatches}
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <div class="card-title"><span class="title-icon">🔍</span> Evidence Verifier</div>
        ${itemsHtml}
      </div>
    `;
  }

  // =========================================================================
  // What-If
  // =========================================================================

  function renderWhatIf(whatif) {
    const items = whatif?.missing_evidence_ranked || [];

    if (!items.length) {
      return `<div class="card"><div class="card-title"><span class="title-icon">🔮</span> What-If Analysis</div><p style="color:var(--text-dim);font-size:13px;">All required evidence submitted.</p></div>`;
    }

    const maxImp = Math.max(...items.map(i => Math.abs(i.expected_improvement)), 0.01);

    const itemsHtml = items.map(item => {
      const pct = (item.expected_improvement * 100).toFixed(1);
      const isPos = item.expected_improvement >= 0;
      const barW = Math.min(Math.abs(item.expected_improvement) / maxImp * 100, 100);

      return `
        <div class="whatif-item">
          <span class="whatif-type">${fmtReason(item.missing_evidence_type)}</span>
          <div class="whatif-right">
            <span class="whatif-improvement ${isPos ? '' : 'negative'}">${isPos ? '+' : ''}${pct}%</span>
            <div class="whatif-bar">
              <div class="whatif-bar-fill" style="width:${barW}%;${!isPos ? 'background:var(--grad-danger);' : ''}"></div>
            </div>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <div class="card-title"><span class="title-icon">🔮</span> What-If Analysis</div>
        <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 14px;">Impact of obtaining missing evidence</p>
        ${itemsHtml}
      </div>
    `;
  }

  // =========================================================================
  // Metrics
  // =========================================================================

  async function updateMetrics() {
    try {
      const res = await fetch(`${API}/api/agent-metrics`);
      const data = await res.json();
      const s = data.session || {};

      document.getElementById('m-total').textContent = s.total_disputes || 0;
      document.getElementById('m-automation').textContent = s.total_disputes
        ? `${(s.automation_coverage * 100).toFixed(0)}%` : '—';
      document.getElementById('m-human-rate').textContent = s.total_disputes
        ? `${(s.human_review_rate * 100).toFixed(0)}%` : '—';
      document.getElementById('m-agent-rate').textContent = s.agent_investigated
        ? `${(s.agent_resolution_rate * 100).toFixed(0)}%` : '—';
      document.getElementById('m-reduction').textContent = s.total_disputes && s.human_review_reduction > 0
        ? `↓${(s.human_review_reduction * 100).toFixed(0)}%` : '—';
    } catch (err) {
      // Silently fail
    }
  }

  // =========================================================================
  // Feedback Modal
  // =========================================================================

  window._openFeedback = function () {
    feedbackModal.classList.remove('hidden');
  };

  document.getElementById('feedback-cancel').addEventListener('click', () => {
    feedbackModal.classList.add('hidden');
  });

  feedbackModal.addEventListener('click', (e) => {
    if (e.target === feedbackModal) feedbackModal.classList.add('hidden');
  });

  document.getElementById('feedback-submit').addEventListener('click', async () => {
    if (!currentAnalysis || !activeId) return;

    const body = {
      ai_recommendation: currentAnalysis.decision?.decision || '',
      human_decision: document.getElementById('feedback-decision').value,
      reason: document.getElementById('feedback-reason').value,
      notes: document.getElementById('feedback-notes').value,
      agent_investigated: !!currentAnalysis.investigation,
    };

    try {
      const res = await fetch(`${API}/api/disputes/${activeId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        feedbackModal.classList.add('hidden');
        document.getElementById('feedback-notes').value = '';
        // Show brief success indicator
        const btn = document.querySelector('.btn-override');
        if (btn) {
          btn.textContent = '✓ Feedback Recorded';
          btn.style.color = 'var(--neon-emerald)';
          btn.style.borderColor = 'rgba(52, 211, 153, 0.2)';
          setTimeout(() => {
            btn.textContent = '✏️ Override Decision';
            btn.style.color = '';
            btn.style.borderColor = '';
          }, 3000);
        }
      }
    } catch (err) {
      console.error('Feedback submission failed:', err);
    }
  });

  // =========================================================================
  // Init
  // =========================================================================

  loadDisputes();
  updateMetrics();
})();
