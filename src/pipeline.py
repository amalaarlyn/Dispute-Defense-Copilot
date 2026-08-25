"""
Inference Pipeline for Dispute Defense Copilot.

Orchestrates the full flow:
Dispute JSON -> Evidence Verifier -> Outcome Predictor -> What-If Engine -> Decision Policy
"""

import sys
import os
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from evidence_verifier import verify_single_document
from outcome_predictor import extract_dispute_features, predict_win_probability
from whatif_engine import run_whatif_analysis
from decision_policy import evaluate_decision_policy
from audit_logger import (
    get_logger,
    log_dispute_analysis,
    log_evidence_verification,
    log_model_loaded,
)

_logger = get_logger(__name__)

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
    Returns a CopilotResponse dict.
    """
    if not dispute_rows:
        return {"error": "No dispute rows provided."}
        
    first_row = dispute_rows[0]
    reason_code = first_row.get("reason_code", "")
    hours_remaining = float(first_row.get("hours_remaining_at_creation", 24))
    
    # 1. Evidence Verifier
    verifier_results = []
    for row in dispute_rows:
        # Check if it has an evidence document (some rows might just be metadata if no docs submitted)
        if row.get("evidence_type"):
            res = verify_single_document(verifier_model, row)
            verifier_results.append(res)
            log_evidence_verification(first_row.get("dispute_id", ""), res)
            
    # Update the rows with verifier outputs before passing to Predictor 
    # (In a real system, the predictor uses the verifier's output. 
    # Here, for the prototype, the predictor uses the synthetic labels to simulate 
    # a perfect verifier for the sake of the predictor's training. We'll use the synthetic
    # labels for feature extraction to keep it simple and aligned with training).
    
    # 2. Outcome Predictor
    dispute_features = extract_dispute_features(dispute_rows)
    win_prob = predict_win_probability(predictor_model, dispute_features)
    
    # 3. What-If Engine
    whatif_results = run_whatif_analysis(predictor_model, dispute_features, reason_code, win_prob)
    
    # 4. Decision Policy
    decision = evaluate_decision_policy(
        win_prob=win_prob,
        evidence_completeness=dispute_features.get("evidence_completeness", 0.0),
        verifier_results=verifier_results,
        whatif_results=whatif_results,
        hours_remaining=hours_remaining
    )
    
    # 5. LLM Explanation Layer (Template-based for prototype)
    narrative = decision["reason"]
    
    response = {
        "dispute_id": first_row.get("dispute_id"),
        "reason_code": reason_code,
        "win_probability": round(win_prob, 4),
        "verifier_results": verifier_results,
        "whatif_results": whatif_results,
        "decision": decision,
        "narrative": narrative,
        "features": dispute_features
    }

    log_dispute_analysis(response["dispute_id"], response)
    _logger.info("Dispute %s analyzed — action=%s, P(win)=%.2f",
                 response["dispute_id"], decision["action"], win_prob)
    return response
