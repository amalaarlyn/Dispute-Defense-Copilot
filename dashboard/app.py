import os
import sys
import json
import csv
import joblib
from flask import Flask, jsonify, request, render_template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from pipeline import analyze_dispute
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
    _logger.info("Dashboard: models loaded successfully")
except FileNotFoundError:
    print("Warning: Models not found. Run src/train.py first.")
    _logger.warning("Models not found — run src/train.py first")

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
        
    # Take just the first 100 for the dashboard to keep it snappy
    sample_dids = list(groups.keys())[:100]
    return {did: groups[did] for did in sample_dids}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/disputes")
def list_disputes():
    data = get_disputes_data()
    # Return just the summary for the list view
    summaries = []
    for did, rows in data.items():
        first = rows[0]
        summaries.append({
            "dispute_id": did,
            "reason_code": first.get("reason_code"),
            "amount": float(first.get("amount", 0)),
            "hours_remaining": float(first.get("hours_remaining_at_creation", 0)),
            "evidence_count": len([r for r in rows if r.get("evidence_type")])
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
    _logger.info("Starting Dispute Defense Copilot dashboard on port 5000")
    app.run(debug=True, port=5000)
