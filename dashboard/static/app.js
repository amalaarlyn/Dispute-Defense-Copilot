/**
 * EVIDRA — AI Evidence Intelligence Dashboard
 * 
 * Features:
 * - Hash-based client-side router with 5 pages
 * - Dashboard home with AI Automation Impact metrics
 * - Disputes page with Case Brief, Next Best Action, Decision Timeline,
 *   Why This Decision, Uncertainty Explanation, AI Investigation
 * - Analytics page with agent performance metrics
 * - Audit Log page with searchable event trail
 * - Settings page with configuration controls
 * - Human feedback modal with override capture
 * - Business language throughout (no ML jargon)
 */

(function () {
  'use strict';

  const API = '';

  // =========================================================================
  // Router
  // =========================================================================

  const PAGES = ['dashboard', 'disputes', 'analytics', 'audit', 'settings'];
  let currentPage = null;
  let pageInitialized = {};

  function initRouter() {
    window.addEventListener('hashchange', () => navigate(getPageFromHash()));
    navigate(getPageFromHash());
  }

  function getPageFromHash() {
    const hash = window.location.hash.replace('#/', '').split('/')[0];
    return PAGES.includes(hash) ? hash : 'dashboard';
  }

  function navigate(page) {
    if (page === currentPage) return;
    const prevPage = currentPage;
    currentPage = page;

    if (window.location.hash !== `#/${page}`) {
      history.replaceState(null, '', `#/${page}`);
    }

    document.querySelectorAll('.nav-rail-item').forEach(el => {
      el.classList.toggle('active', el.dataset.page === page);
    });

    PAGES.forEach(p => {
      const el = document.getElementById(`page-${p}`);
      if (!el) return;
      if (p === page) {
        el.classList.remove('hidden');
        el.classList.add('page-entering');
        setTimeout(() => el.classList.remove('page-entering'), 350);
      } else {
        el.classList.add('hidden');
        el.classList.remove('page-entering');
      }
    });

    loadPageData(page);
  }

  function loadPageData(page) {
    switch (page) {
      case 'dashboard':
        loadDashboard();
        break;
      case 'disputes':
        if (!pageInitialized.disputes) {
          loadDisputes();
          pageInitialized.disputes = true;
        }
        break;
      case 'analytics':
        loadAnalytics();
        break;
      case 'audit':
        loadAuditLog();
        break;
      case 'settings':
        initSettings();
        break;
    }
  }

  // =========================================================================
  // Dashboard Page
  // =========================================================================

  async function loadDashboard() {
    try {
      const [metricsRes, disputesRes, modelRes, impactRes] = await Promise.allSettled([
        fetch(`${API}/api/agent-metrics`),
        fetch(`${API}/api/disputes`),
        fetch(`${API}/api/metrics`),
        fetch(`${API}/api/automation-impact`),
      ]);

      // Agent Metrics
      if (metricsRes.status === 'fulfilled' && metricsRes.value.ok) {
        const data = await metricsRes.value.json();
        const s = data.session || {};
        
        animateDashMetric('dm-total', s.total_disputes || 0, false);
        animateDashMetric('dm-automation', s.total_disputes ? `${(s.automation_coverage * 100).toFixed(0)}%` : '—');
        animateDashMetric('dm-human', s.total_disputes ? `${(s.human_review_rate * 100).toFixed(0)}%` : '—');
        animateDashMetric('dm-reduction', s.total_disputes && s.human_review_reduction > 0 ? `↓${(s.human_review_reduction * 100).toFixed(0)}%` : '—');

        updateMetrics(data);
      }

      // Automation Impact Card
      if (impactRes.status === 'fulfilled' && impactRes.value.ok) {
        const impact = await impactRes.value.json();
        renderAutomationImpact(impact);
      }

      // Recent Disputes
      if (disputesRes.status === 'fulfilled' && disputesRes.value.ok) {
        const disputes = await disputesRes.value.json();
        renderRecentDisputes(disputes.slice(0, 8));
      }

      // Model Metrics
      if (modelRes.status === 'fulfilled' && modelRes.value.ok) {
        const modelData = await modelRes.value.json();
        renderDashModelMetrics(modelData);
      }
    } catch (err) {
      console.error('Dashboard load error:', err);
    }
  }

  function animateDashMetric(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
  }

  function renderAutomationImpact(impact) {
    const container = document.getElementById('automation-impact-content');
    if (!container) return;

    if (!impact.disputes_analyzed) {
      container.innerHTML = `
        <div style="grid-column:span 4; text-align:center; padding:20px; color:var(--text-dim); font-size:13px;">
          Analyze disputes to see AI automation impact metrics.
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="impact-stat">
        <div class="impact-stat-value indigo">${impact.disputes_analyzed}</div>
        <div class="impact-stat-label">Disputes Analyzed</div>
      </div>
      <div class="impact-stat">
        <div class="impact-stat-value emerald">${impact.ai_resolved_automatically}</div>
        <div class="impact-stat-label">AI Resolved</div>
      </div>
      <div class="impact-stat">
        <div class="impact-stat-value amber">${impact.human_reviews_required}</div>
        <div class="impact-stat-label">Human Reviews</div>
      </div>
      <div class="impact-stat">
        <div class="impact-stat-value cyan">${impact.human_review_reduction > 0 ? `↓${impact.human_review_reduction}%` : '—'}</div>
        <div class="impact-stat-label">Review Reduction</div>
      </div>
      ${impact.human_review_reduction > 0 ? `
        <div class="impact-highlight">
          <span class="impact-highlight-text">Human review reduced by</span>
          <span class="impact-highlight-value">${impact.human_review_reduction}%</span>
          <span class="impact-highlight-text">compared to baseline</span>
        </div>
      ` : ''}
    `;
  }

  function renderRecentDisputes(disputes) {
    const container = document.getElementById('dash-recent-list');
    if (!container) return;

    if (!disputes.length) {
      container.innerHTML = '<div class="loading">No disputes found.</div>';
      return;
    }

    container.innerHTML = disputes.map(d => {
      const shortId = d.dispute_id.replace('disp_', '').substring(0, 10);
      return `
        <div class="dash-recent-item" data-id="${d.dispute_id}">
          <div>
            <span class="recent-id">disp_${shortId}…</span>
          </div>
          <div class="recent-meta">
            <span class="recent-amount">₹${Number(d.amount).toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
            <span class="recent-badge ${d.has_tamper ? 'tamper' : ''}">${d.has_tamper ? '⚠ Tamper' : fmtReason(d.reason_code)}</span>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.dash-recent-item').forEach(el => {
      el.addEventListener('click', () => {
        window.location.hash = '#/disputes';
        setTimeout(() => selectDispute(el.dataset.id), 100);
      });
    });
  }

  function renderDashModelMetrics(data) {
    const container = document.getElementById('dash-model-metrics');
    if (!container) return;

    const metrics = [];
    if (data.outcome_predictor) {
      const op = data.outcome_predictor;
      if (op.roc_auc !== undefined) metrics.push({ label: 'Predictor AUC', value: op.roc_auc.toFixed(3) });
      if (op.accuracy !== undefined) metrics.push({ label: 'Predictor Accuracy', value: `${(op.accuracy * 100).toFixed(1)}%` });
    }
    if (data.evidence_verifier) {
      const ev = data.evidence_verifier;
      if (ev.roc_auc !== undefined) metrics.push({ label: 'Verifier AUC', value: ev.roc_auc.toFixed(3) });
      if (ev.accuracy !== undefined) metrics.push({ label: 'Verifier Accuracy', value: `${(ev.accuracy * 100).toFixed(1)}%` });
    }

    if (!metrics.length) {
      container.innerHTML = '<div style="font-size:12px;color:var(--text-dim);padding:8px 0;">No model metrics available.</div>';
      return;
    }

    container.innerHTML = metrics.map(m => `
      <div class="dash-model-metric-row">
        <span class="dash-model-metric-label">${m.label}</span>
        <span class="dash-model-metric-value">${m.value}</span>
      </div>
    `).join('');
  }

  document.getElementById('btn-refresh-dashboard')?.addEventListener('click', () => {
    loadDashboard();
  });

  // =========================================================================
  // Disputes Page — List
  // =========================================================================

  const disputeListEl = document.getElementById('dispute-list');
  const searchInput = document.getElementById('search-input');
  const analysisView = document.getElementById('analysis-view');
  const emptyState = document.getElementById('empty-state');
  const feedbackModal = document.getElementById('feedback-modal');

  let allDisputes = [];
  let activeId = null;
  let currentAnalysis = null;

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

  let searchTimeout;
  searchInput?.addEventListener('input', () => {
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
  // Disputes Page — Select & Analyze
  // =========================================================================

  async function selectDispute(disputeId) {
    activeId = disputeId;

    if (currentPage !== 'disputes') {
      window.location.hash = '#/disputes';
    }

    if (!allDisputes.length) {
      await loadDisputes();
    }

    disputeListEl.querySelectorAll('.dispute-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === disputeId);
    });

    emptyState.classList.add('hidden');
    analysisView.classList.remove('hidden');
    analysisView.innerHTML = renderSkeleton();

    setAgentStatus('investigating');

    try {
      const res = await fetch(`${API}/api/disputes/${disputeId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      currentAnalysis = data;
      renderAnalysis(data);
      setAgentStatus('online');
      updateMetricsFromApi();
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
      text.textContent = 'Investigating…';
    } else {
      dot.className = 'status-dot online';
      text.textContent = 'System Online';
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

    const amountLog = data.features?.amount_log || 0;
    const amount = Math.expm1(amountLog);
    const hoursRemaining = data.features?.hours_remaining || 0;

    analysisView.innerHTML = `
      ${renderHero(data, amount, hoursRemaining)}
      ${renderPipeline(data.pipeline_stages || [])}
      <div class="grid-2">
        <div>
          ${renderRecommendation(data, decision, hasAgent, agentResolved)}
          ${renderCaseBrief(data.case_brief)}
          ${renderGauge(data.win_probability)}
          ${renderWhyDecision(data.why_decision)}
          ${hasAgent ? renderInvestigation(investigation) : ''}
          ${humanBrief ? renderHumanBrief(humanBrief) : ''}
          ${renderUncertaintyExplanation(data.uncertainty_explanation)}
        </div>
        <div>
          ${renderNextBestAction(data.whatif_results, data.win_probability)}
          ${renderEvidence(data.verifier_results)}
          ${renderDecisionTimeline(data.decision_timeline)}
        </div>
      </div>
    `;

    requestAnimationFrame(() => animateGauge(data.win_probability));
    animatePipeline(data.pipeline_stages || []);
  }

  // =========================================================================
  // Hero Card
  // =========================================================================

  function renderHero(data, amount, hoursRemaining) {
    const validCount = (data.verifier_results || []).filter(r => r.predicted_valid).length;
    const totalCount = (data.verifier_results || []).length;
    const missing = data.whatif_results?.missing_evidence_ranked || [];
    const requiredTotal = totalCount + missing.length;

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
            <span class="hero-stat-label">Contest Likelihood</span>
            <span class="hero-stat-value probability">${(data.win_probability * 100).toFixed(1)}%</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Evidence</span>
            <span class="hero-stat-value evidence">${totalCount}/${requiredTotal} submitted</span>
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
        <div class="pipeline-label">EVIDRA Pipeline</div>
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
      'recommend_contest': '✅ RECOMMEND: CONTEST',
      'recommend_accept': '❌ RECOMMEND: ACCEPT',
      'human_review': '👤 HUMAN REVIEW REQUIRED',
      'recommend_obtain_evidence': '📋 GATHER MORE EVIDENCE',
      'agent_investigation': '🤖 AI INVESTIGATING',
    };

    const agentTag = hasAgent
      ? agentResolved
        ? '<span class="agent-badge">🤖 Resolved by EVIDRA</span>'
        : '<span class="agent-badge">🤖 Investigated by EVIDRA</span>'
      : '';

    const overrideBtn = `<button class="btn btn-override" onclick="window._openFeedback()">✏️ Override</button>`;

    return `
      <div class="card glass-panel recommendation-card ${decision}">
        <div class="card-title"><span class="title-icon">⚖️</span> Recommendation</div>
        <div class="action-badge ${decision}">${labels[decision] || decision}</div>
        <p class="narrative">${data.decision?.reason || data.narrative || ''}</p>
        ${agentTag}
        <div style="margin-top:14px;">${overrideBtn}</div>
      </div>
    `;
  }

  // =========================================================================
  // AI Case Brief
  // =========================================================================

  function renderCaseBrief(brief) {
    if (!brief) return '';

    return `
      <div class="card glass-panel case-brief-card">
        <div class="card-title"><span class="title-icon">📝</span> AI Case Brief</div>
        <div class="case-brief-text">${brief}</div>
      </div>
    `;
  }

  // =========================================================================
  // Gauge
  // =========================================================================

  function renderGauge(winProb) {
    return `
      <div class="card glass-panel" style="text-align:center;">
        <div class="card-title" style="justify-content:center;"><span class="title-icon">📊</span> Contest Likelihood</div>
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
  // Why This Decision
  // =========================================================================

  function renderWhyDecision(why) {
    if (!why) return '';

    return `
      <div class="card glass-panel why-decision-card">
        <div class="card-title"><span class="title-icon">❓</span> Why This Decision?</div>
        <div class="why-decision-grid">
          <div class="why-metric">
            <div class="why-metric-label">Evidence Strength</div>
            <div class="why-metric-value">${why.evidence_strength || '—'}</div>
          </div>
          <div class="why-metric">
            <div class="why-metric-label">Completeness</div>
            <div class="why-metric-value">${why.evidence_completeness || '—'}</div>
          </div>
          <div class="why-metric">
            <div class="why-metric-label">Contest Probability</div>
            <div class="why-metric-value">${why.contest_probability || '—'}</div>
          </div>
          <div class="why-metric">
            <div class="why-metric-label">Loss if Contest</div>
            <div class="why-metric-value" style="color:var(--neon-rose);">${why.expected_loss_contest || '—'}</div>
          </div>
          <div class="why-metric">
            <div class="why-metric-label">Loss if Accept</div>
            <div class="why-metric-value" style="color:var(--neon-amber);">${why.expected_loss_accept || '—'}</div>
          </div>
          <div class="why-metric">
            <div class="why-metric-label">Time Remaining</div>
            <div class="why-metric-value" style="color:var(--neon-cyan);">${why.time_remaining || '—'}</div>
          </div>
        </div>
        <div class="why-conclusion">${why.conclusion || ''}</div>
      </div>
    `;
  }

  // =========================================================================
  // AI Investigation Panel
  // =========================================================================

  function renderInvestigation(inv) {
    if (!inv) return '';

    const status = inv.status === 'resolved' ? 'resolved' : 'escalated';
    const statusLabel = status === 'resolved' ? '✓ Resolved' : '⚠ Escalated to Human';
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
          <div class="inv-step-title">✓ ${s.description}</div>
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

    const uncertainty = inv.uncertainty_analysis || {};
    const primaryType = uncertainty.primary_uncertainty || '';
    const overallSeverity = uncertainty.overall_severity || 0;

    return `
      <div class="card glass-panel investigation-card">
        <div class="investigation-header">
          <div class="agent-icon">🤖</div>
          <h3>AI Investigation</h3>
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
      <div class="card glass-panel human-brief-card" style="position:relative;">
        <div class="card-title"><span class="title-icon">📋</span> AI Investigation Brief for Human</div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">${brief.summary || ''}</p>
        
        ${alreadyHtml ? `
          <div class="brief-section">
            <div class="brief-section-title">✅ Already Investigated by EVIDRA</div>
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
  // Next Best Action (replaces raw What-If)
  // =========================================================================

  function renderNextBestAction(whatif, currentWinProb) {
    const items = whatif?.missing_evidence_ranked || [];

    if (!items.length) {
      return `<div class="card glass-panel"><div class="card-title"><span class="title-icon">🎯</span> Next Best Action</div><p style="color:var(--text-dim);font-size:13px;">All required evidence submitted. No further action needed.</p></div>`;
    }

    const best = items[0];
    const currentPct = (currentWinProb * 100).toFixed(0);
    const projectedPct = ((currentWinProb + best.expected_improvement) * 100).toFixed(0);
    const deltaPct = (best.expected_improvement * 100).toFixed(0);
    const evidenceType = fmtReason(best.missing_evidence_type);

    // Additional missing evidence as smaller items
    const otherItems = items.slice(1).map(item => {
      const pct = (item.expected_improvement * 100).toFixed(1);
      const isPos = item.expected_improvement >= 0;
      return `
        <div class="whatif-item">
          <span class="whatif-type">${fmtReason(item.missing_evidence_type)}</span>
          <div class="whatif-right">
            <span class="whatif-improvement ${isPos ? '' : 'negative'}">${isPos ? '+' : ''}${pct}%</span>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="card glass-panel next-best-action-card">
        <div class="card-title"><span class="title-icon">🎯</span> Next Best Action</div>
        <div class="nba-content">
          <div class="nba-action-name">Get ${evidenceType}</div>
          <div class="nba-probability-row">
            <div class="nba-prob-box">
              <div class="nba-prob-label">Current</div>
              <div class="nba-prob-value current">${currentPct}%</div>
            </div>
            <div class="nba-arrow">
              <span class="nba-delta">+${deltaPct}%</span>
              <span class="nba-arrow-icon">→</span>
            </div>
            <div class="nba-prob-box">
              <div class="nba-prob-label">Projected</div>
              <div class="nba-prob-value projected">${projectedPct}%</div>
            </div>
          </div>
          <div class="nba-reason">
            <strong>Why?</strong> ${evidenceType} directly addresses the dispute reason and has the highest expected impact among currently missing evidence.
            Assumed validity of new document: ${(best.assumed_validity_rate_of_new_doc * 100).toFixed(0)}%.
          </div>
          <div class="nba-actions">
            <button class="btn-action" onclick="alert('Simulated Action: Fetching ' + '${evidenceType}' + ' from internal databases...')">📎 Find Evidence</button>
            <button class="btn-action" onclick="alert('Simulated Action: Drafting automated evidence request email to merchant for ' + '${evidenceType}' + '...')">📧 Generate Request</button>
          </div>
        </div>
        ${otherItems ? `
          <div style="margin-top:16px; border-top:1px solid var(--border-subtle); padding-top:14px;">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-dim);font-weight:600;margin-bottom:10px;">Other Missing Evidence</div>
            ${otherItems}
          </div>
        ` : ''}
      </div>
    `;
  }

  // =========================================================================
  // Evidence Verifier
  // =========================================================================

  function renderEvidence(results) {
    if (!results || !results.length) {
      return `<div class="card glass-panel"><div class="card-title"><span class="title-icon">🔍</span> Evidence Verifier</div><p style="color:var(--text-dim);font-size:13px;">No evidence submitted.</p></div>`;
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
      <div class="card glass-panel">
        <div class="card-title"><span class="title-icon">🔍</span> Evidence Analysis</div>
        ${itemsHtml}
      </div>
    `;
  }

  // =========================================================================
  // Decision Timeline
  // =========================================================================

  function renderDecisionTimeline(timeline) {
    if (!timeline || !timeline.length) return '';

    const itemsHtml = timeline.map(t => {
      const time = new Date(t.timestamp).toLocaleTimeString();
      return `
        <div class="timeline-item">
          <div class="timeline-line">
            <div class="timeline-dot"></div>
            <div class="timeline-connector"></div>
          </div>
          <div class="timeline-content">
            <div class="timeline-event">${t.event}</div>
            <div class="timeline-detail">${t.detail}</div>
            <div class="timeline-time">${time}</div>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="card glass-panel timeline-card">
        <div class="card-title"><span class="title-icon">⏱️</span> Decision Timeline</div>
        <div class="decision-timeline">${itemsHtml}</div>
      </div>
    `;
  }

  // =========================================================================
  // Uncertainty Explanation
  // =========================================================================

  function renderUncertaintyExplanation(ue) {
    if (!ue) return '';

    const badgeClass = (ue.confidence_level || 'medium').toLowerCase();
    const badgeLabels = { high: 'HIGH CONFIDENCE', medium: 'MEDIUM CONFIDENCE', low: 'LOW CONFIDENCE' };

    const confirmedHtml = (ue.confirmed || []).map(c => `
      <div class="uncertainty-item">
        <span class="uncertainty-icon">✓</span>
        <span>${c}</span>
      </div>
    `).join('');

    const concernsHtml = (ue.concerns || []).map(c => `
      <div class="uncertainty-item">
        <span class="uncertainty-icon">⚠</span>
        <span>${c}</span>
      </div>
    `).join('');

    return `
      <div class="card glass-panel uncertainty-card">
        <div class="card-title"><span class="title-icon">🤖</span> Why Am I ${badgeClass === 'high' ? 'Confident' : 'Uncertain'}?</div>
        <div class="confidence-badge ${badgeClass}">${badgeLabels[badgeClass] || 'UNKNOWN'}</div>
        
        ${confirmedHtml ? `
          <div class="uncertainty-section">
            <div class="uncertainty-section-title">The system found</div>
            ${confirmedHtml}
          </div>
        ` : ''}
        
        ${concernsHtml ? `
          <div class="uncertainty-section">
            <div class="uncertainty-section-title">However</div>
            ${concernsHtml}
          </div>
        ` : ''}
        
        ${ue.recommendation ? `
          <div class="uncertainty-recommendation">💡 ${ue.recommendation}</div>
        ` : ''}
      </div>
    `;
  }

  // =========================================================================
  // Analytics Page
  // =========================================================================

  async function loadAnalytics() {
    const container = document.getElementById('analytics-content');
    if (!container) return;

    container.innerHTML = '<div class="loading">Loading analytics…</div>';

    try {
      const [metricsRes, modelRes] = await Promise.allSettled([
        fetch(`${API}/api/agent-metrics`),
        fetch(`${API}/api/metrics`),
      ]);

      let html = '';

      if (metricsRes.status === 'fulfilled' && metricsRes.value.ok) {
        const data = await metricsRes.value.json();
        const s = data.session || {};
        const fb = data.feedback || {};

        html += `
          <div class="analytics-grid">
            <div class="analytics-stat-card">
              <div class="stat-content">
                  <div class="analytics-stat-label">Total Disputes</div>
                  <div class="analytics-stat-value indigo">${s.total_disputes || 0}</div>
                  <div class="analytics-stat-sub">Processed by EVIDRA</div>
              </div>
              <div class="stat-chart-placeholder"></div>
            </div>
            
            <div class="analytics-stat-card">
              <div class="stat-content">
                  <div class="analytics-stat-label">Automation Rate</div>
                  <div class="analytics-stat-value emerald">${s.total_disputes ? `${(s.automation_coverage * 100).toFixed(1)}%` : '—'}</div>
                  <div class="analytics-stat-sub">Disputes auto-resolved</div>
              </div>
              <div class="stat-ring">
                  <svg viewBox="0 0 100 100" class="ring-svg">
                      <circle cx="50" cy="50" r="40" class="ring-bg"></circle>
                      <circle cx="50" cy="50" r="40" class="ring-fg emerald" stroke-dasharray="251.2" stroke-dashoffset="${251.2 * (1 - (s.automation_coverage || 0))}"></circle>
                  </svg>
              </div>
            </div>

            <div class="analytics-stat-card">
              <div class="stat-content">
                  <div class="analytics-stat-label">Human Review Rate</div>
                  <div class="analytics-stat-value amber">${s.total_disputes ? `${(s.human_review_rate * 100).toFixed(1)}%` : '—'}</div>
                  <div class="analytics-stat-sub">Escalated to humans</div>
              </div>
              <div class="stat-ring">
                  <svg viewBox="0 0 100 100" class="ring-svg">
                      <circle cx="50" cy="50" r="40" class="ring-bg"></circle>
                      <circle cx="50" cy="50" r="40" class="ring-fg amber" stroke-dasharray="251.2" stroke-dashoffset="${251.2 * (1 - (s.human_review_rate || 0))}"></circle>
                  </svg>
              </div>
            </div>

            <div class="analytics-stat-card">
              <div class="stat-content">
                  <div class="analytics-stat-label">AI Investigated</div>
                  <div class="analytics-stat-value violet">${s.agent_investigated || 0}</div>
                  <div class="analytics-stat-sub">Uncertainty investigations</div>
              </div>
              <div class="stat-chart-placeholder"></div>
            </div>

            <div class="analytics-stat-card">
              <div class="stat-content">
                  <div class="analytics-stat-label">AI Resolution Rate</div>
                  <div class="analytics-stat-value emerald">${s.total_disputes ? `${((s.agent_resolved / (s.agent_investigated || 1)) * 100).toFixed(1)}%` : '—'}</div>
                  <div class="analytics-stat-sub">Resolved without human</div>
              </div>
              <div class="stat-ring">
                  <svg viewBox="0 0 100 100" class="ring-svg">
                      <circle cx="50" cy="50" r="40" class="ring-bg"></circle>
                      <circle cx="50" cy="50" r="40" class="ring-fg emerald" stroke-dasharray="251.2" stroke-dashoffset="${251.2 * (1 - ((s.agent_resolved || 0) / (s.agent_investigated || 1)))}"></circle>
                  </svg>
              </div>
            </div>

            <div class="analytics-stat-card">
              <div class="stat-content">
                  <div class="analytics-stat-label">Review Reduction</div>
                  <div class="analytics-stat-value rose">↓${s.human_review_reduction > 0 ? `${(s.human_review_reduction * 100).toFixed(1)}%` : '0%'}</div>
                  <div class="analytics-stat-sub">Less human workload</div>
              </div>
              <div class="stat-ring">
                  <svg viewBox="0 0 100 100" class="ring-svg">
                      <circle cx="50" cy="50" r="40" class="ring-bg"></circle>
                      <circle cx="50" cy="50" r="40" class="ring-fg rose" stroke-dasharray="251.2" stroke-dashoffset="${251.2 * (1 - (s.human_review_reduction || 0))}"></circle>
                  </svg>
              </div>
            </div>
          </div>
        `;

        if (fb.total_overrides !== undefined) {
          const reasons = fb.reason_distribution || {};
          const maxCount = Math.max(...Object.values(reasons), 1);
          const colors = ['indigo', 'emerald', 'amber', 'rose', 'cyan'];

          html += `
            <div class="card glass-panel">
              <div class="card-title"><span class="title-icon">📝</span> Human Override Feedback</div>
              <div class="analytics-grid" style="grid-template-columns: repeat(3, 1fr); margin-bottom: 20px;">
                <div>
                  <div class="analytics-stat-label">Total Overrides</div>
                  <div style="font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--neon-amber);">${fb.total_overrides || 0}</div>
                </div>
                <div>
                  <div class="analytics-stat-label">Agreement Rate</div>
                  <div style="font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--neon-emerald);">${fb.agreement_rate !== undefined ? `${(fb.agreement_rate * 100).toFixed(0)}%` : '—'}</div>
                </div>
                <div>
                  <div class="analytics-stat-label">Override Rate</div>
                  <div style="font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--neon-rose);">${fb.override_rate !== undefined ? `${(fb.override_rate * 100).toFixed(0)}%` : '—'}</div>
                </div>
              </div>
              ${Object.keys(reasons).length ? `
                <div class="analytics-section-title">Override Reasons</div>
                <div class="feedback-bar-chart">
                  ${Object.entries(reasons).map(([reason, count], idx) => `
                    <div class="fb-bar-row">
                      <span class="fb-bar-label">${fmtReason(reason)}</span>
                      <div class="fb-bar-track">
                        <div class="fb-bar-fill ${colors[idx % colors.length]}" style="width:${(count / maxCount * 100).toFixed(0)}%"></div>
                      </div>
                      <span class="fb-bar-count">${count}</span>
                    </div>
                  `).join('')}
                </div>
              ` : ''}
            </div>
          `;
        }
      }

      if (modelRes.status === 'fulfilled' && modelRes.value.ok) {
        const modelData = await modelRes.value.json();
        
        const renderModelTable = (name, data) => {
          if (!data || typeof data !== 'object') return '';
          const rows = Object.entries(data).filter(([k, v]) => typeof v === 'number').map(([k, v]) => `
            <tr>
              <td>${fmtReason(k)}</td>
              <td class="metric-val">${v < 1 ? v.toFixed(4) : v.toFixed(2)}</td>
            </tr>
          `).join('');

          if (!rows) return '';

          return `
            <div class="card glass-panel">
              <div class="card-title"><span class="title-icon">🧠</span> ${name}</div>
              <table class="model-perf-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
          `;
        };

        const grid2Html = [];
        if (modelData.outcome_predictor) grid2Html.push(renderModelTable('Outcome Predictor', modelData.outcome_predictor));
        if (modelData.evidence_verifier) grid2Html.push(renderModelTable('Evidence Verifier', modelData.evidence_verifier));

        if (grid2Html.length) {
          html += `<div class="grid-2">${grid2Html.join('')}</div>`;
        }
      }

      container.innerHTML = html || '<div class="loading">No analytics data available. Analyze some disputes first.</div>';
    } catch (err) {
      container.innerHTML = `<div class="loading" style="color:var(--neon-rose);">Failed to load analytics: ${err.message}</div>`;
    }
  }

  // =========================================================================
  // Audit Log Page
  // =========================================================================

  async function loadAuditLog() {
    const container = document.getElementById('audit-content');
    if (!container) return;

    const disputeId = document.getElementById('audit-search')?.value.trim() || '';
    const eventType = document.getElementById('audit-type-filter')?.value || '';

    container.innerHTML = '<div class="loading">Loading audit log…</div>';

    try {
      let url = `${API}/api/audit-log?limit=200`;
      if (disputeId) url += `&dispute_id=${encodeURIComponent(disputeId)}`;
      if (eventType) url += `&event_type=${encodeURIComponent(eventType)}`;

      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      const entries = data.entries || [];
      
      if (!entries.length) {
        container.innerHTML = `
          <div class="card glass-panel">
            <div class="audit-empty">
              <p>No audit entries found.</p>
              <p style="font-size:12px;margin-top:8px;">Analyze some disputes to generate audit trail entries.</p>
            </div>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <div class="audit-count">${entries.length} entries found</div>
        <div class="card glass-panel" style="padding:0;overflow:hidden;">
          <div class="audit-table-wrapper">
            <table class="audit-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Event Type</th>
                  <th>Dispute ID</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                ${entries.map(e => {
                  const eventClass = ['api_request', 'model_loaded', 'feedback'].includes(e.event_type) ? e.event_type : 'default';
                  const details = [];
                  if (e.method) details.push(e.method);
                  if (e.path) details.push(e.path);
                  if (e.status_code) details.push(`HTTP ${e.status_code}`);
                  if (e.model_name) details.push(`Model: ${e.model_name}`);
                  if (e.message) details.push(e.message);
                  
                  return `
                    <tr>
                      <td class="audit-timestamp">${e.timestamp ? new Date(e.timestamp).toLocaleString() : '—'}</td>
                      <td><span class="audit-event-type ${eventClass}">${fmtReason(e.event_type || 'unknown')}</span></td>
                      <td class="audit-id">${e.dispute_id || '—'}</td>
                      <td style="color:var(--text-muted);font-size:12px;">${details.join(' · ') || '—'}</td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div class="loading" style="color:var(--neon-rose);">Failed to load audit log: ${err.message}</div>`;
    }
  }

  document.getElementById('btn-refresh-audit')?.addEventListener('click', loadAuditLog);
  
  let auditSearchTimeout;
  document.getElementById('audit-search')?.addEventListener('input', () => {
    clearTimeout(auditSearchTimeout);
    auditSearchTimeout = setTimeout(loadAuditLog, 400);
  });

  document.getElementById('audit-type-filter')?.addEventListener('change', loadAuditLog);

  // =========================================================================
  // Settings Page
  // =========================================================================

  let settingsInitialized = false;

  function initSettings() {
    if (settingsInitialized) return;
    settingsInitialized = true;

    const uncertaintySlider = document.getElementById('setting-uncertainty');
    const uncertaintyVal = document.getElementById('setting-uncertainty-val');
    if (uncertaintySlider && uncertaintyVal) {
      uncertaintySlider.addEventListener('input', () => {
        uncertaintyVal.textContent = (uncertaintySlider.value / 100).toFixed(2);
      });
    }

    const confidenceSlider = document.getElementById('setting-confidence');
    const confidenceVal = document.getElementById('setting-confidence-val');
    if (confidenceSlider && confidenceVal) {
      confidenceSlider.addEventListener('input', () => {
        confidenceVal.textContent = (confidenceSlider.value / 100).toFixed(2);
      });
    }
  }

  // =========================================================================
  // Metrics (Bottom Ribbon)
  // =========================================================================

  function updateMetrics(data) {
    if (!data) return;
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
  }

  async function updateMetricsFromApi() {
    try {
      const res = await fetch(`${API}/api/agent-metrics`);
      const data = await res.json();
      updateMetrics(data);
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

  document.getElementById('feedback-cancel')?.addEventListener('click', () => {
    feedbackModal.classList.add('hidden');
  });

  feedbackModal?.addEventListener('click', (e) => {
    if (e.target === feedbackModal) feedbackModal.classList.add('hidden');
  });

  document.getElementById('feedback-submit')?.addEventListener('click', async () => {
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
        const btn = document.querySelector('.btn-override');
        if (btn) {
          btn.textContent = '✓ Feedback Recorded';
          btn.style.color = 'var(--neon-emerald)';
          btn.style.borderColor = 'rgba(52, 211, 153, 0.2)';
          setTimeout(() => {
            btn.textContent = '✏️ Override';
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

  initRouter();
  updateMetricsFromApi();
})();
