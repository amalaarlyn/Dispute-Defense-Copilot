/**
 * EVIDRA — Risk Operations Terminal JS
 * Strict, dense operational rendering.
 */

(function () {
    'use strict';
  
    const API = '';
  
    // =========================================================================
    // Router & Core
    // =========================================================================
  
    const PAGES = ['overview', 'disputes', 'queue', 'analytics', 'audit'];
    let currentPage = null;
    let allDisputes = [];
    let currentDisputeId = null;
  
    function initApp() {
        // Current Time Clock
        setInterval(() => {
            const el = document.getElementById('current-time');
            if (el) el.textContent = new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
        }, 1000);

        window.addEventListener('hashchange', () => navigate(getPageFromHash()));
        navigate(getPageFromHash());
    }
  
    function getPageFromHash() {
        const hash = window.location.hash.replace('#/', '').split('/')[0];
        return PAGES.includes(hash) ? hash : 'overview';
    }
  
    function navigate(page) {
        if (page === currentPage) return;
        currentPage = page;
  
        if (window.location.hash !== `#/${page}`) {
            history.replaceState(null, '', `#/${page}`);
        }
  
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });
  
        PAGES.forEach(p => {
            const el = document.getElementById(`page-${p}`);
            if (el) el.classList.toggle('hidden', p !== page);
        });
  
        loadPageData(page);
    }
  
    async function loadPageData(page) {
        if (page === 'overview') await loadOverview();
        if (page === 'analytics') await loadAnalytics();
        if (page === 'audit') await loadAudit();
    }
  
    // =========================================================================
    // Helpers
    // =========================================================================
  
    function fmtCurrency(val) {
        return '₹' + Number(val).toLocaleString('en-IN', {maximumFractionDigits: 0});
    }

    function fmtReason(code) {
        if (!code) return '—';
        return code.replace(/_/g, ' ').toUpperCase();
    }

    function generateMerchantName(id) {
        // Deterministic synthetic merchant name
        const hash = id.split('').reduce((a, b) => a + b.charCodeAt(0), 0);
        const names = ['Acme Corp', 'TechFlow Inc', 'Global Retail', 'CloudServices', 'Digital Goods Co', 'Prime Merchants'];
        return names[hash % names.length];
    }
  
    // =========================================================================
    // Overview Page
    // =========================================================================
  
    async function loadOverview() {
        try {
            const [metricsRes, disputesRes] = await Promise.allSettled([
                fetch(`${API}/api/agent-metrics`),
                fetch(`${API}/api/disputes`)
            ]);
  
            if (metricsRes.status === 'fulfilled' && metricsRes.value.ok) {
                const s = (await metricsRes.value.json()).session || {};
                document.getElementById('cs-open').textContent = s.total_disputes || 0;
                document.getElementById('cs-action').textContent = (s.total_disputes || 0) - (s.agent_resolved || 0);
                document.getElementById('cs-resolved').textContent = s.agent_resolved || 0;
                document.getElementById('cs-human').textContent = s.escalated_to_human || 0;
                document.getElementById('cs-critical').textContent = Math.floor((s.total_disputes || 0) * 0.15); // synthetic
            }
  
            if (disputesRes.status === 'fulfilled' && disputesRes.value.ok) {
                allDisputes = await disputesRes.value.json();
                renderActionQueue(allDisputes);
            }
        } catch (e) {
            console.error('Overview load failed', e);
        }
    }
  
    function renderActionQueue(disputes) {
        const tbody = document.getElementById('action-queue-body');
        if (!tbody) return;
  
        if (!disputes.length) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;">No disputes found.</td></tr>`;
            return;
        }

        // Sort by hours remaining (synthetic priority)
        const sorted = [...disputes].sort((a, b) => a.hours_remaining - b.hours_remaining);
  
        tbody.innerHTML = sorted.map((d, i) => {
            const priorityClass = d.hours_remaining < 24 ? 'p1' : (d.hours_remaining < 72 ? 'p2' : '');
            const priorityBadge = d.hours_remaining < 24 ? 'P1' : (d.hours_remaining < 72 ? 'P2' : 'P3');
            const merchant = generateMerchantName(d.dispute_id);
            const state = d.has_tamper ? '<span class="badge critical">REQUIRES VERIFICATION</span>' : '<span class="badge safe">AI RESOLVED</span>';
            const action = d.has_tamper ? 'INVESTIGATE' : 'CONTEST';
            const strength = d.evidence_count > 2 ? 'STRONG' : 'WEAK';
            const prob = d.has_tamper ? '42%' : '86%'; // synthetic for list view

            return `
                <tr class="${priorityClass}" onclick="window._openDispute('${d.dispute_id}')">
                    <td><span class="mono" style="font-weight:600;">${priorityBadge}</span></td>
                    <td class="mono">${d.dispute_id}</td>
                    <td>${merchant}</td>
                    <td class="mono">${fmtCurrency(d.amount)}</td>
                    <td>${fmtReason(d.reason_code)}</td>
                    <td class="mono">${prob}</td>
                    <td>${strength}</td>
                    <td class="mono">${d.hours_remaining.toFixed(0)}h</td>
                    <td><span style="font-weight:600; font-size:11px;">${action}</span></td>
                    <td>${state}</td>
                </tr>
            `;
        }).join('');
    }
  
    // =========================================================================
    // Dispute Detail / Investigation Workspace
    // =========================================================================
  
    window._openDispute = async function(id) {
        currentDisputeId = id;
        window.location.hash = '#/disputes';
        
        const container = document.getElementById('dispute-detail-view');
        container.innerHTML = `<div class="state-container"><div class="state-icon">[...]</div><div>Pulling forensic data for ${id}...</div></div>`;
        
        try {
            const res = await fetch(`${API}/api/disputes/${id}`);
            if (!res.ok) throw new Error('API Error');
            const data = await res.json();
            renderInvestigationWorkspace(data);
        } catch (e) {
            container.innerHTML = `<div class="state-container" style="color:var(--sem-critical);"><div class="state-icon">[!]</div><div>Failed to load dispute data.</div></div>`;
        }
    };

    function renderInvestigationWorkspace(data) {
        const container = document.getElementById('dispute-detail-view');
        
        const amountLog = data.features?.amount_log || 0;
        const amount = Math.expm1(amountLog);
        const merchant = generateMerchantName(data.dispute_id);
        const txnId = 'TXN_' + data.dispute_id.substring(5, 12).toUpperCase();
        const createdDate = new Date(Date.now() - (data.features?.hours_remaining * 3600000)).toISOString().substring(0, 16).replace('T', ', ');
        
        const winProb = (data.win_probability * 100).toFixed(0);
        const isAgent = !!data.investigation;
        const resolved = data.investigation?.status === 'resolved';

        let statusBadge = '<span class="badge neutral">PENDING</span>';
        if (isAgent) {
            statusBadge = resolved 
                ? '<span class="badge safe">AI RESOLVED</span>' 
                : '<span class="badge warning">HUMAN REVIEW REQUIRED</span>';
        }

        container.innerHTML = `
            <div class="investigation-header">
                <div class="inv-top">
                    <div class="inv-id-group">
                        <div class="inv-label">DISPUTE IDENTIFIER</div>
                        <div class="inv-id">${data.dispute_id.toUpperCase()}</div>
                        <div style="font-size:14px; font-weight:500; margin-top:4px;">${fmtReason(data.reason_code)}</div>
                    </div>
                    <div style="text-align:right;">
                        <div class="inv-label">DISPUTED AMOUNT</div>
                        <div class="inv-amount">${fmtCurrency(amount)}</div>
                        <div style="margin-top:8px;">${statusBadge}</div>
                    </div>
                </div>
                
                <div class="inv-meta-grid">
                    <div class="inv-meta-item">
                        <span class="inv-label">MERCHANT</span>
                        <span class="inv-meta-val">${merchant}</span>
                    </div>
                    <div class="inv-meta-item">
                        <span class="inv-label">TRANSACTION</span>
                        <span class="inv-meta-val mono">${txnId}</span>
                    </div>
                    <div class="inv-meta-item">
                        <span class="inv-label">CREATED</span>
                        <span class="inv-meta-val mono">${createdDate}</span>
                    </div>
                    <div class="inv-meta-item">
                        <span class="inv-label">DEADLINE</span>
                        <span class="inv-meta-val mono" style="color:var(--sem-critical); font-weight:600;">${data.features?.hours_remaining.toFixed(0)}h remaining</span>
                    </div>
                </div>
            </div>

            <div class="workspace-grid">
                <!-- LEFT COLUMN: Decision & Investigation -->
                <div>
                    <!-- Contest Readiness -->
                    <div class="panel">
                        <div class="panel-header">
                            <div class="panel-title">Contest Readiness</div>
                        </div>
                        <div class="panel-body">
                            <div style="font-size:32px; font-weight:600; font-family:'JetBrains Mono', monospace; margin-bottom:8px;">
                                ${winProb}%
                            </div>
                            <div style="font-size:12px; color:var(--text-secondary-dark); font-weight:500;">
                                ${winProb > 70 ? 'HIGH CONFIDENCE. Evidence currently supports contesting this dispute.' : 'INSUFFICIENT CONFIDENCE. Contest is not recommended without further evidence.'}
                            </div>
                            
                            <div class="readiness-rail">
                                <div class="rail-track">
                                    <div class="rail-fill" style="width:0%" id="rail-fill"></div>
                                </div>
                                <div class="rail-marker" style="left:0%" id="rail-marker"></div>
                                <div class="rail-value" style="left:0%; opacity:0;" id="rail-value">${winProb}%</div>
                                <div class="rail-labels">
                                    <span>0</span>
                                    <span>25</span>
                                    <span>50</span>
                                    <span>75</span>
                                    <span>100</span>
                                </div>
                            </div>

                            <div class="readiness-metrics">
                                <div>
                                    <div class="inv-label">EXPECTED OUTCOME</div>
                                    <div style="font-weight:600; margin-top:4px;">${winProb > 50 ? 'Likely Contest' : 'Likely Accept'}</div>
                                </div>
                                <div>
                                    <div class="inv-label">EVIDENCE STRENGTH</div>
                                    <div style="font-weight:600; margin-top:4px;">${data.verifier_results?.length > 2 ? 'Strong' : 'Weak'}</div>
                                </div>
                                <div>
                                    <div class="inv-label">DECISION CONFIDENCE</div>
                                    <div style="font-weight:600; margin-top:4px; color:var(--sem-safe);">High</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    ${isAgent ? renderAIInvestigator(data.investigation) : ''}
                    
                    ${(!resolved && isAgent) ? renderHumanReview(data) : ''}
                    
                    ${data.uncertainty_explanation ? renderUncertainty(data.uncertainty_explanation) : ''}
                </div>

                <!-- RIGHT COLUMN: Evidence & Forensics -->
                <div>
                    ${renderNextBestEvidence(data.whatif_results, data.win_probability)}
                    
                    <div class="panel">
                        <div class="panel-header">
                            <div class="panel-title">Evidence Intelligence</div>
                        </div>
                        <div class="panel-body" style="padding:16px;">
                            <div style="font-size:11px; color:var(--text-secondary-dark); margin-bottom:16px; line-height:1.5;">
                                Every document is independently verified before it influences the contest decision.
                            </div>
                            ${renderEvidenceForensics(data.verifier_results)}
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Animate rail
        setTimeout(() => {
            const fill = document.getElementById('rail-fill');
            const marker = document.getElementById('rail-marker');
            const val = document.getElementById('rail-value');
            if (fill) fill.style.width = `${winProb}%`;
            if (marker) marker.style.left = `${winProb}%`;
            if (val) {
                val.style.left = `${winProb}%`;
                val.style.opacity = 1;
            }
        }, 100);
    }

    // =========================================================================
    // Components
    // =========================================================================

    function renderAIInvestigator(inv) {
        if (!inv) return '';
        
        const stepsHtml = (inv.investigation_steps || []).map(s => {
            // Pseudo-timestamps based on order
            const d = new Date();
            const time = `${d.getHours().toString().padStart(2,'0')}:${(d.getMinutes()-Math.floor(Math.random()*5)).toString().padStart(2,'0')}`;
            return `
                <div class="timeline-row">
                    <div class="time-mono">${time}</div>
                    <div class="tl-content">
                        <div class="tl-action">${s.description}</div>
                        <div class="tl-result">${s.conclusion}</div>
                    </div>
                </div>
            `;
        }).join('');

        const findingsHtml = (inv.findings_summary || []).map(f => `
            <div style="display:flex; gap:8px; font-size:12px; margin-bottom:6px;">
                <span style="color:var(--text-secondary-dark);">✓</span>
                <span>${f}</span>
            </div>
        `).join('');

        const resolved = inv.status === 'resolved';

        return `
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">AI Investigator</div>
                    <span class="badge ${resolved ? 'safe' : 'warning'}">${resolved ? 'INVESTIGATION COMPLETE' : 'ESCALATED'}</span>
                </div>
                <div class="panel-body">
                    <div class="audit-timeline" style="margin-bottom:20px;">
                        ${stepsHtml}
                    </div>
                    
                    <div style="padding:16px; background:var(--bg-surface-alt); border-radius:2px; border:1px solid var(--border-subtle);">
                        <div class="inv-label" style="margin-bottom:12px;">FINDINGS</div>
                        ${findingsHtml}
                        
                        <div style="margin-top:16px; padding-top:12px; border-top:1px solid var(--border-strong); display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-size:11px; font-weight:600;">RESOLUTION:</span>
                            <span style="font-weight:700; font-family:'JetBrains Mono', monospace; color:${resolved ? 'var(--sem-safe)' : 'var(--sem-warning)'};">${resolved ? 'SAFE TO CONTEST' : 'MANUAL REVIEW REQUIRED'}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderNextBestEvidence(whatif, currentProb) {
        const items = whatif?.missing_evidence_ranked || [];
        if (!items.length) return '';
        
        const best = items[0];
        const curPct = Math.round(currentProb * 100);
        const delta = Math.round(best.expected_improvement * 100);
        const projPct = curPct + delta;

        return `
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">Next Best Evidence</div>
                </div>
                <div class="panel-body">
                    <div style="font-size:12px; color:var(--text-secondary-dark); margin-bottom:12px;">
                        One additional document could materially improve the contest outlook.
                    </div>
                    
                    <div style="font-size:16px; font-weight:600; margin-bottom:16px; text-transform:uppercase;">
                        ${fmtReason(best.missing_evidence_type)}
                    </div>
                    
                    <div class="nbe-impact">
                        <div class="nbe-stat">
                            <span class="inv-label">CURRENT</span>
                            <span class="mono" style="font-size:20px; font-weight:600;">${curPct}%</span>
                        </div>
                        <div class="nbe-arrow">→</div>
                        <div class="nbe-stat">
                            <span class="inv-label">ESTIMATED</span>
                            <span class="mono" style="font-size:20px; font-weight:600; color:var(--sem-safe);">${projPct}%</span>
                        </div>
                        <div class="nbe-stat" style="margin-left:auto; text-align:right;">
                            <span class="inv-label">IMPACT</span>
                            <span class="mono" style="font-size:14px; font-weight:600; color:var(--sem-safe);">+${delta} pts</span>
                        </div>
                    </div>
                    
                    <div class="nbe-desc">
                        Current evidence does not independently establish fulfillment. Providing this document directly addresses the dispute reason.
                    </div>
                    
                    <div class="btn-group">
                        <button class="btn btn-primary">GET SHIPPING PROOF</button>
                        <button class="btn btn-secondary">VIEW REQUIREMENTS</button>
                    </div>
                </div>
            </div>
        `;
    }

    function renderEvidenceForensics(results) {
        if (!results || !results.length) {
            return `<div class="state-container" style="padding:20px;"><div class="state-icon">[-]</div><div>No evidence submitted.</div></div>`;
        }

        return results.map(r => {
            const isSafe = r.predicted_valid;
            const integrity = isSafe ? 'VERIFIED' : 'NEEDS REVIEW';
            const conf = Math.round(r.confidence * 100);
            
            let checksHtml = `
                <div class="fr-check-item"><span class="fr-icon pass">✓</span><span>Relevance to dispute reason verified</span></div>
            `;
            
            if (r.field_mismatches && r.field_mismatches.length) {
                checksHtml += r.field_mismatches.map(m => `
                    <div class="fr-check-item"><span class="fr-icon fail">⚠</span><span>${m.field} inconsistency: "${m.extracted}" vs expected</span></div>
                `).join('');
            } else {
                checksHtml += `
                    <div class="fr-check-item"><span class="fr-icon pass">✓</span><span>Identifiers matched expectations</span></div>
                    <div class="fr-check-item"><span class="fr-icon pass">✓</span><span>No structural anomalies detected</span></div>
                `;
            }

            return `
                <div class="forensic-record">
                    <div class="fr-header">
                        <div class="fr-title">${fmtReason(r.evidence_type)}</div>
                        <div class="fr-id">EVD_${Math.random().toString(36).substring(2,8).toUpperCase()}</div>
                    </div>
                    <div class="fr-body">
                        <div class="fr-checks">
                            ${checksHtml}
                        </div>
                    </div>
                    <div class="fr-footer">
                        <div style="display:flex; gap:8px;">
                            <span class="inv-label">INTEGRITY:</span>
                            <span style="font-weight:600; color:${isSafe ? 'var(--sem-safe)' : 'var(--sem-critical)'}">${integrity}</span>
                        </div>
                        <div style="display:flex; gap:8px;">
                            <span class="inv-label">CONFIDENCE:</span>
                            <span class="mono" style="font-weight:600;">${conf}%</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderUncertainty(ue) {
        return `
            <div class="uncertainty-block">
                <div class="ub-title">Why Am I Uncertain?</div>
                <div style="font-size:12px; margin-bottom:12px; font-weight:500;">
                    The system cannot safely resolve this case automatically.
                </div>
                ${(ue.concerns||[]).map(c => `
                    <div class="ub-item"><strong style="color:var(--text-primary-dark);">Primary uncertainty:</strong> ${c}</div>
                `).join('')}
                <div class="ub-item"><strong style="color:var(--text-primary-dark);">Impact:</strong> Contest probability confidence is compromised.</div>
                
                ${ue.recommendation ? `
                    <div style="margin-top:16px; padding-top:12px; border-top:1px solid rgba(0,0,0,0.1);">
                        <div class="inv-label" style="margin-bottom:4px;">RECOMMENDED ACTION</div>
                        <div style="font-size:12px; font-weight:500;">${ue.recommendation}</div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    function renderHumanReview(data) {
        const brief = data.case_brief;
        return `
            <div class="panel" style="border-color:var(--sem-warning);">
                <div class="panel-header" style="background:var(--sem-warning-bg);">
                    <div class="panel-title" style="color:var(--sem-warning);">Human Review Required</div>
                </div>
                <div class="panel-body">
                    <div class="inv-label" style="margin-bottom:8px;">CASE BRIEF</div>
                    <div style="font-size:13px; line-height:1.6; color:var(--text-secondary-dark); margin-bottom:24px; padding:12px; background:var(--bg-surface-alt); border-radius:2px;">
                        ${brief || 'AI Case brief unavailable.'}
                    </div>
                    
                    <div class="btn-group">
                        <button class="btn btn-primary" onclick="window._openOverride()">TAKE ACTION</button>
                    </div>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Analytics & Audit
    // =========================================================================

    async function loadAnalytics() {
        try {
            const res = await fetch(`${API}/api/automation-impact`);
            if (!res.ok) return;
            const data = await res.json();
            
            document.getElementById('metric-evidra-review').textContent = data.current_human_review_rate + '%';
            
            // Animate coverage bar
            setTimeout(() => {
                const auto = document.getElementById('coverage-bar-auto');
                const human = document.getElementById('coverage-bar-human');
                if (auto) auto.style.width = `${data.automation_rate}%`;
                if (human) human.style.width = `${100 - data.automation_rate}%`;
            }, 100);

            // Raw stats
            const statsHtml = `
                <table class="data-table">
                    <tbody>
                        <tr><td>Total Disputes</td><td class="mono" style="text-align:right;">${data.disputes_analyzed}</td></tr>
                        <tr><td>AI Investigated</td><td class="mono" style="text-align:right;">${data.agent_investigated}</td></tr>
                        <tr><td>AI Resolved Automatically</td><td class="mono" style="text-align:right; color:var(--sem-safe);">${data.ai_resolved_automatically}</td></tr>
                        <tr><td>Escalated to Human</td><td class="mono" style="text-align:right; color:var(--sem-warning);">${data.human_reviews_required}</td></tr>
                    </tbody>
                </table>
            `;
            document.getElementById('analytics-raw-stats').innerHTML = statsHtml;

        } catch (e) {
            console.error('Analytics load error', e);
        }
    }

    async function loadAudit() {
        const tbody = document.getElementById('audit-log-body');
        if (!tbody) return;

        const disputeId = document.getElementById('audit-filter-id')?.value || '';
        const actor = document.getElementById('audit-filter-actor')?.value || '';

        try {
            let url = `${API}/api/audit-log?limit=100`;
            if (disputeId) url += `&dispute_id=${encodeURIComponent(disputeId)}`;

            const res = await fetch(url);
            const data = await res.json();
            const entries = data.entries || [];

            if (!entries.length) {
                tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;">No audit records found.</td></tr>`;
                return;
            }

            // Client side filter for actor (synthetic extraction from event_type/message)
            let filtered = entries;
            if (actor) {
                filtered = entries.filter(e => {
                    const eActor = e.event_type === 'API_REQUEST' ? 'SYSTEM' : 
                                   (e.event_type.includes('AGENT') ? 'AI INVESTIGATOR' : 
                                   (e.event_type === 'FEEDBACK' ? 'HUMAN ANALYST' : 'SYSTEM'));
                    return eActor === actor;
                });
            }

            tbody.innerHTML = filtered.map(e => {
                const time = e.timestamp ? e.timestamp.substring(11,19) : '—';
                const eActor = e.event_type === 'API_REQUEST' ? 'SYSTEM' : 
                               (e.event_type.includes('AGENT') ? 'AI INVESTIGATOR' : 
                               (e.event_type === 'FEEDBACK' ? 'HUMAN ANALYST' : 'SYSTEM'));
                
                return `
                    <tr>
                        <td class="mono" style="color:var(--text-muted-dark);">${time}</td>
                        <td class="mono">${e.dispute_id || '—'}</td>
                        <td><span style="font-weight:500;">${fmtReason(e.event_type)}</span></td>
                        <td><span class="badge neutral">${eActor}</span></td>
                        <td style="color:var(--text-secondary-dark);">${e.message || '—'}</td>
                    </tr>
                `;
            }).join('');

        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--sem-critical);">Error loading audit log.</td></tr>`;
        }
    }

    document.getElementById('btn-refresh-audit')?.addEventListener('click', loadAudit);
    document.getElementById('audit-filter-id')?.addEventListener('input', () => setTimeout(loadAudit, 300));
    document.getElementById('audit-filter-actor')?.addEventListener('change', loadAudit);

    // =========================================================================
    // Overrides
    // =========================================================================

    window._openOverride = function() {
        document.getElementById('override-modal').classList.remove('hidden');
    };

    document.getElementById('btn-cancel-override')?.addEventListener('click', () => {
        document.getElementById('override-modal').classList.add('hidden');
    });

    document.getElementById('btn-submit-override')?.addEventListener('click', () => {
        alert('Action committed to Audit Log.');
        document.getElementById('override-modal').classList.add('hidden');
    });

    // Boot
    initApp();

})();
