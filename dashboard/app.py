"""
EVIDRA — Dashboard API Server.

Flask application serving the EVIDRA dashboard UI and REST API endpoints.

Endpoints:
    GET  /                          — Dashboard UI
    GET  /api/disputes              — List all disputes (summary)
    GET  /api/disputes/<id>         — Full pipeline analysis for a dispute
    POST /api/disputes/<id>/feedback — Submit human override feedback
    GET  /api/agent-metrics         — Agent performance metrics
    GET  /api/automation-impact     — AI automation impact metrics
    GET  /api/metrics               — Model evaluation metrics
    GET  /api/audit-log             — Query the audit trail
"""

import os
import sys
import json
import csv
import joblib
from flask import Flask, jsonify, request, render_template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from pipeline import analyze_dispute
from human_feedback import record_feedback, get_feedback_stats, OVERRIDE_REASONS
from metrics_tracker import get_session_metrics, get_historical_metrics
from audit_logger import (
    get_logger,
    log_api_request,
    log_model_loaded,
    read_audit_trail,
)

_logger = get_logger(__name__)

app = Flask(__name__)

# Load models at startup
MODELS_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')
DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'synthetic_disputes.csv')

verifier_model = None
predictor_model = None

try:
    verifier_model = joblib.load(os.path.join(MODELS_DIR, "evidence_verifier.joblib"))
    predictor_model = joblib.load(os.path.join(MODELS_DIR, "outcome_predictor.joblib"))
    log_model_loaded("evidence_verifier", os.path.join(MODELS_DIR, "evidence_verifier.joblib"))
    log_model_loaded("outcome_predictor", os.path.join(MODELS_DIR, "outcome_predictor.joblib"))
    _logger.info("EVIDRA: models loaded successfully")
except FileNotFoundError:
    print("Warning: Models not found. Run src/train.py first.")
    _logger.warning("Models not found — run src/train.py first")

_simulated_evidence = {}

def get_disputes_data():
    if not os.path.exists(DATA_PATH):
        return []
        
    with open(DATA_PATH, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
    # Group by dispute_id
    groups = {}
    for r in rows:
        did = r["dispute_id"]
        if did not in groups:
            groups[did] = []
        groups[did].append(r)
        
    # Inject simulated evidence
    for did, new_evidence_rows in _simulated_evidence.items():
        if did in groups:
            groups[did].extend(new_evidence_rows)
            
    # Take first 100 for the dashboard
    sample_dids = list(groups.keys())[:100]
    return {did: groups[did] for did in sample_dids}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/disputes")
def list_disputes():
    data = get_disputes_data()
    summaries = []
    for did, rows in data.items():
        first = rows[0]
        has_tamper = any(
            r.get("tamper_flag_label") in (True, "True", "true", 1, "1")
            for r in rows
        )
        summaries.append({
            "dispute_id": did,
            "reason_code": first.get("reason_code"),
            "amount": float(first.get("amount", 0)),
            "hours_remaining": float(first.get("hours_remaining_at_creation", 0)),
            "evidence_count": len([r for r in rows if r.get("evidence_type")]),
            "has_tamper": has_tamper,
        })
    return jsonify(summaries)

@app.route("/api/disputes/<dispute_id>")
def get_dispute_analysis(dispute_id):
    data = get_disputes_data()
    if dispute_id not in data:
        return jsonify({"error": "Not found"}), 404
        
    rows = data[dispute_id]
    
    if not verifier_model or not predictor_model:
        return jsonify({"error": "Models not loaded"}), 500
        
    analysis = analyze_dispute(rows, verifier_model, predictor_model)
    log_api_request("GET", f"/api/disputes/{dispute_id}", 200, dispute_id=dispute_id)
    return jsonify(analysis)

@app.route("/api/disputes/<dispute_id>/feedback", methods=["POST"])
def submit_feedback(dispute_id):
    """Submit human override feedback for a dispute."""
    body = request.get_json(force=True)
    
    if not body:
        return jsonify({"error": "Request body required"}), 400
    
    ai_recommendation = body.get("ai_recommendation", "")
    human_decision = body.get("human_decision", "")
    reason = body.get("reason", "other")
    notes = body.get("notes", "")
    agent_investigated = body.get("agent_investigated", False)
    
    if not human_decision:
        return jsonify({"error": "human_decision is required"}), 400
    
    entry = record_feedback(
        dispute_id=dispute_id,
        ai_recommendation=ai_recommendation,
        human_decision=human_decision,
        reason=reason,
        notes=notes,
        agent_investigated=agent_investigated,
    )
    
    _logger.info("Feedback recorded for dispute %s: AI=%s → Human=%s (reason=%s)",
                 dispute_id, ai_recommendation, human_decision, reason)
    
    return jsonify({"status": "recorded", "feedback": entry})

@app.route("/api/disputes/<dispute_id>/find-evidence", methods=["POST"])
def find_evidence(dispute_id):
    """Simulate finding missing evidence in internal CRM/Billing systems."""
    body = request.get_json(force=True)
    evidence_type = body.get("evidence_type")
    
    if not evidence_type:
        return jsonify({"error": "evidence_type is required"}), 400
        
    data = get_disputes_data()
    if dispute_id not in data:
        return jsonify({"error": "Dispute not found"}), 404
        
    base_row = data[dispute_id][0]
    
    # Create a simulated row for the newly found evidence
    simulated_row = base_row.copy()
    simulated_row["evidence_type"] = evidence_type
    simulated_row["evidence_is_valid_label"] = "True"
    simulated_row["tamper_flag_label"] = "False"
    
    if dispute_id not in _simulated_evidence:
        _simulated_evidence[dispute_id] = []
        
    # Check if we already injected this type to avoid duplicates
    existing = [r for r in _simulated_evidence[dispute_id] if r["evidence_type"] == evidence_type]
    if not existing:
        _simulated_evidence[dispute_id].append(simulated_row)
        _logger.info("Simulated finding evidence %s for dispute %s", evidence_type, dispute_id)
        
    return jsonify({"status": "success", "message": f"Successfully retrieved {evidence_type} from internal systems."})

@app.route("/api/disputes/<dispute_id>/generate-request", methods=["POST"])
def generate_request(dispute_id):
    """Simulate drafting and sending an email request to the merchant."""
    body = request.get_json(force=True)
    evidence_type = body.get("evidence_type")
    
    if not evidence_type:
        return jsonify({"error": "evidence_type is required"}), 400
        
    _logger.info("Simulated sending request for %s for dispute %s", evidence_type, dispute_id)
    return jsonify({"status": "success", "message": f"Automated email requesting {evidence_type} drafted and queued for delivery."})

@app.route("/api/agent-metrics")
def get_agent_metrics():
    """Get agent performance metrics (session + historical)."""
    session = get_session_metrics().to_dict()
    historical = get_historical_metrics()
    feedback = get_feedback_stats()
    
    return jsonify({
        "session": session,
        "historical": historical,
        "feedback": feedback,
    })

@app.route("/api/automation-impact")
def get_automation_impact():
    """Get the AI automation impact metrics — the headline business metric.
    
    Returns:
        disputes_analyzed: total disputes processed
        ai_resolved_automatically: disputes resolved without human
        human_reviews_required: disputes that needed human review
        human_review_reduction: % reduction vs baseline
        baseline_comparison: what it would have been without the AI agent
    """
    session = get_session_metrics()
    s = session.to_dict()
    
    return jsonify({
        "disputes_analyzed": s["total_disputes"],
        "ai_resolved_automatically": s["auto_resolved"] + s["agent_resolved"],
        "human_reviews_required": s["escalated_to_human"],
        "human_review_reduction": round(s["human_review_reduction"] * 100, 1),
        "automation_rate": round(s["automation_coverage"] * 100, 1),
        "agent_investigated": s["agent_investigated"],
        "agent_resolved": s["agent_resolved"],
        "agent_resolution_rate": round(s["agent_resolution_rate"] * 100, 1),
        "baseline_human_review_rate": round(s["baseline_human_review_rate"] * 100, 1),
        "current_human_review_rate": round(s["human_review_rate"] * 100, 1),
    })

@app.route("/api/feedback-options")
def get_feedback_options():
    """Get available feedback reason categories."""
    return jsonify({
        "reasons": OVERRIDE_REASONS,
        "decisions": [
            "contest",
            "accept",
            "obtain_evidence",
            "human_review",
        ],
    })

@app.route("/api/metrics")
def get_metrics():
    metrics_path = os.path.join(MODELS_DIR, "evaluation_report.json")
    if os.path.exists(metrics_path):
        with open(metrics_path, "r") as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route("/api/audit-log")
def get_audit_log():
    """Query the audit trail with optional filters."""
    dispute_id = request.args.get("dispute_id")
    event_type = request.args.get("event_type")
    limit = request.args.get("limit", 200, type=int)

    entries = read_audit_trail(
        dispute_id=dispute_id,
        event_type=event_type,
        limit=limit,
    )
    return jsonify({"count": len(entries), "entries": entries})

if __name__ == "__main__":
    _logger.info("Starting EVIDRA dashboard on port 8080")
    app.run(debug=True, port=8080)
