"""
EVIDRA — Inference Pipeline.

Orchestrates the full flow:
Dispute JSON -> Evidence Verifier -> Outcome Predictor -> What-If Engine
-> Decision Policy -> [AI Case Investigator if ambiguous] -> Final Decision
-> Case Brief + Intelligence Layer

The AI Case Investigator is the key upgrade: instead of routing ambiguous
cases directly to human review, the agent investigates uncertainty using
structured tools and resolves what it can. Only truly unresolvable cases
reach a human — and those come with a structured investigation brief.
"""

import sys
import os
import time
import joblib
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from evidence_verifier import verify_single_document
from outcome_predictor import extract_dispute_features, predict_win_probability
from what_if_engine import WhatIfEngine
from decision_policy import decide, WHATIF_TIME_THRESHOLD_HOURS
from contest_outcome_features import build_dispute_level_features
from case_resolution_agent import CaseResolutionAgent
from metrics_tracker import get_session_metrics
from llm_explanation import (
    generate_case_brief,
    generate_uncertainty_explanation,
    generate_why_decision,
)
from audit_logger import (
    get_logger,
    log_dispute_analysis,
    log_evidence_verification,
    log_model_loaded,
)

_logger = get_logger(__name__)

# Lazily initialised singletons
_whatif_engine = None
_case_agent = None


def _get_whatif_engine():
    global _whatif_engine
    if _whatif_engine is None:
        _whatif_engine = WhatIfEngine()
    return _whatif_engine


def _get_case_agent():
    global _case_agent
    if _case_agent is None:
        _case_agent = CaseResolutionAgent()
    return _case_agent


def load_models(model_dir):
    """Load the trained models."""
    verifier_path = os.path.join(model_dir, "evidence_verifier.joblib")
    predictor_path = os.path.join(model_dir, "outcome_predictor.joblib")
    verifier = joblib.load(verifier_path)
    predictor = joblib.load(predictor_path)
    log_model_loaded("evidence_verifier", verifier_path)
    log_model_loaded("outcome_predictor", predictor_path)
    _logger.info("Models loaded from %s", model_dir)
    return verifier, predictor


def analyze_dispute(dispute_rows, verifier_model, predictor_model):
    """
    Run the end-to-end pipeline on a single dispute's rows.

    Now includes Case Resolution Agent for ambiguous cases:
      1. Evidence Verifier — per-document validation
      2. Outcome Predictor — dispute-level win probability
      3. What-If Engine — rank missing evidence by impact
      4. Decision Policy — initial recommendation
      5. Case Resolution Agent — investigates if decision is "agent_investigation"
      6. Final recommendation — either agent-resolved or human-escalated
      7. Intelligence Layer — Case Brief, Uncertainty Explanation, Why Decision

    Returns a CopilotResponse dict.
    """
    if not dispute_rows:
        return {"error": "No dispute rows provided."}

    pipeline_start = time.time()
    timeline = []

    first_row = dispute_rows[0]
    reason_code = first_row.get("reason_code", "")
    hours_remaining = float(first_row.get("hours_remaining_at_creation", 24))
    amount = float(first_row.get("amount", 0))
    dispute_id = first_row.get("dispute_id", "")

    metrics = get_session_metrics()

    _add_timeline(timeline, "Dispute received", f"₹{amount:,.0f} — {reason_code.replace('_', ' ').title()}")

    # 1. Evidence Verifier — per-document validation
    t1 = time.time()
    verifier_results = []
    for row in dispute_rows:
        if row.get("evidence_type"):
            res = verify_single_document(verifier_model, row)
            verifier_results.append(res)
            log_evidence_verification(dispute_id, res)

    valid_count = sum(1 for r in verifier_results if r.get("predicted_valid"))
    _add_timeline(timeline, "Evidence analyzed", f"{valid_count}/{len(verifier_results)} documents verified")

    # 2. Outcome Predictor — dispute-level win probability
    dispute_features = extract_dispute_features(dispute_rows)
    win_prob = predict_win_probability(predictor_model, dispute_features)
    _add_timeline(timeline, "Contest probability calculated", f"{win_prob:.0%} win probability")

    # 3. What-If Engine — rank missing evidence by projected impact
    try:
        evidence_df = pd.DataFrame(dispute_rows)
        dispute_level_feats = build_dispute_level_features(evidence_df, verifier=verifier_model)
        current_features = dispute_level_feats.iloc[0].to_dict()
        submitted_types = set(
            row.get("evidence_type", "") for row in dispute_rows if row.get("evidence_type")
        )
        engine = _get_whatif_engine()
        whatif_results = engine.analyze(current_features, reason_code, submitted_types)
    except Exception as e:
        _logger.warning("What-if engine failed for %s: %s", dispute_id, e)
        whatif_results = {"current_win_prob": round(win_prob, 3), "missing_evidence_ranked": []}

    missing_count = len(whatif_results.get("missing_evidence_ranked", []))
    if missing_count > 0:
        _add_timeline(timeline, "Missing evidence identified", f"{missing_count} evidence gap{'s' if missing_count != 1 else ''} found")

    _add_timeline(timeline, "What-if analysis completed", f"{missing_count} scenario{'s' if missing_count != 1 else ''} analyzed")

    # 4. Decision Policy — initial recommendation
    best_improvement = 0.0
    if whatif_results.get("missing_evidence_ranked"):
        best_improvement = whatif_results["missing_evidence_ranked"][0].get("expected_improvement", 0.0)

    has_time = hours_remaining > WHATIF_TIME_THRESHOLD_HOURS
    any_tamper = int(any(
        r.get("tamper_flag_label") in (True, "True", "true", 1, "1")
        for r in dispute_rows
    ))

    decision = decide(
        win_prob=win_prob,
        amount=amount,
        hours_remaining=hours_remaining,
        any_tamper_flagged=any_tamper,
        best_whatif_improvement=best_improvement,
        has_time_for_more_evidence=has_time,
    )

    # 5. Case Resolution Agent — investigate if decision is "agent_investigation"
    investigation = None
    if decision["decision"] == "agent_investigation":
        _add_timeline(timeline, "AI investigation started", "Investigating uncertainty sources")

        agent = _get_case_agent()
        investigation_report = agent.investigate(
            dispute_id=dispute_id,
            win_probability=win_prob,
            amount=amount,
            hours_remaining=hours_remaining,
            reason_code=reason_code,
            verifier_results=verifier_results,
            whatif_results=whatif_results,
            dispute_rows=dispute_rows,
            original_decision=decision["decision"],
        )
        investigation = investigation_report.to_dict()

        # 6. Update decision based on agent findings
        if investigation_report.status == "resolved":
            # Agent resolved the ambiguity!
            decision = {
                "decision": investigation_report.final_recommendation,
                "reason": investigation_report.final_reason,
                "agent_resolved": True,
                "agent_confidence": investigation_report.confidence,
            }
            metrics.record_agent_resolution(investigation_report.final_recommendation.replace("recommend_", ""))
            _add_timeline(timeline, "AI investigation resolved", f"Ambiguity resolved → {investigation_report.final_recommendation.replace('recommend_', '').replace('_', ' ').title()}")
            _logger.info("Agent RESOLVED dispute %s → %s", dispute_id, decision["decision"])
        else:
            # Agent could not resolve → escalate to human with brief
            decision = {
                "decision": "human_review",
                "reason": investigation_report.final_reason,
                "agent_investigated": True,
                "agent_confidence": investigation_report.confidence,
                "human_brief": investigation_report.human_brief,
            }
            metrics.record_agent_escalation()
            _add_timeline(timeline, "Escalated to human review", "AI could not resolve uncertainty")
            _logger.info("Agent ESCALATED dispute %s to human review", dispute_id)
    else:
        # Direct decision (no agent needed)
        metrics.record_auto_decision(decision["decision"])

    _add_timeline(timeline, "Recommendation generated", decision.get("decision", "").replace("_", " ").replace("recommend ", "").title())

    # 7. Intelligence Layer — Case Brief, Uncertainty, Why Decision
    case_brief = generate_case_brief(
        dispute_id=dispute_id,
        reason_code=reason_code,
        amount=amount,
        hours_remaining=hours_remaining,
        win_probability=win_prob,
        verifier_results=verifier_results,
        whatif_results=whatif_results,
        decision=decision,
        investigation=investigation,
    )

    uncertainty_explanation = generate_uncertainty_explanation(
        win_probability=win_prob,
        verifier_results=verifier_results,
        whatif_results=whatif_results,
        investigation=investigation,
    )

    why_decision = generate_why_decision(
        win_probability=win_prob,
        amount=amount,
        hours_remaining=hours_remaining,
        verifier_results=verifier_results,
        whatif_results=whatif_results,
        decision=decision,
    )

    # 8. Narrative
    narrative = case_brief  # Use the case brief as the primary narrative

    response = {
        "dispute_id": dispute_id,
        "reason_code": reason_code,
        "win_probability": round(win_prob, 4),
        "verifier_results": verifier_results,
        "whatif_results": whatif_results,
        "decision": decision,
        "investigation": investigation,
        "narrative": narrative,
        "case_brief": case_brief,
        "uncertainty_explanation": uncertainty_explanation,
        "why_decision": why_decision,
        "decision_timeline": timeline,
        "features": dispute_features,
        "pipeline_stages": _build_pipeline_stages(
            verifier_results, win_prob, whatif_results, decision, investigation
        ),
    }

    log_dispute_analysis(response["dispute_id"], response)
    _logger.info("Dispute %s analyzed — action=%s, P(win)=%.2f",
                 response["dispute_id"], decision["decision"], win_prob)
    return response


def _add_timeline(timeline: list, event: str, detail: str):
    """Add a timestamped event to the decision timeline."""
    timeline.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "detail": detail,
    })


def _build_pipeline_stages(verifier_results, win_prob, whatif_results, decision, investigation):
    """Build a list of pipeline stages for the dashboard animation."""
    stages = [
        {
            "name": "Evidence Intake",
            "icon": "📄",
            "status": "completed",
            "summary": f"{len(verifier_results)} document(s) received",
        },
        {
            "name": "Evidence Verifier",
            "icon": "🔍",
            "status": "completed",
            "summary": f"{sum(1 for r in verifier_results if r.get('predicted_valid'))}/{len(verifier_results)} valid",
        },
        {
            "name": "Outcome Predictor",
            "icon": "📊",
            "status": "completed",
            "summary": f"{win_prob:.0%} contest likelihood",
        },
        {
            "name": "What-If Engine",
            "icon": "🔮",
            "status": "completed",
            "summary": f"{len(whatif_results.get('missing_evidence_ranked', []))} scenario(s) analyzed",
        },
        {
            "name": "Decision Engine",
            "icon": "⚖️",
            "status": "completed",
            "summary": decision.get("decision", "").replace("_", " ").replace("recommend ", "").title(),
        },
    ]

    if investigation:
        agent_status = "completed"
        agent_summary = (
            f"{'Resolved' if investigation.get('status') == 'resolved' else 'Escalated'} — "
            f"{len(investigation.get('investigation_steps', []))} check(s) performed"
        )
        stages.append({
            "name": "AI Investigator",
            "icon": "🤖",
            "status": agent_status,
            "summary": agent_summary,
        })

    return stages
