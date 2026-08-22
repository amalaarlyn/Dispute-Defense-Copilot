"""
Evidence What-If Engine for Dispute Defense Copilot.

For each missing required evidence type, simulates adding it, re-scores with
the Outcome Predictor, and computes the marginal increase in win probability.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from schema import EvidenceType, REASON_TO_REQUIRED_EVIDENCE, ReasonCode
from outcome_predictor import predict_win_probability

def run_whatif_analysis(model, base_features, reason_code_str, current_prob):
    """
    Given the base features of a dispute and the current predicted win probability,
    simulate adding each missing required evidence type to see the impact.
    
    Returns a sorted list of dicts: 
    [{"evidence_type": "...", "projected_prob": 0.xx, "delta": +0.xx}]
    """
    try:
        reason_code = ReasonCode(reason_code_str)
        required = [et.value for et in REASON_TO_REQUIRED_EVIDENCE.get(reason_code, [])]
    except (ValueError, KeyError):
        return []
    
    missing_required = [et for et in required if base_features.get(f"has_{et}", 0.0) == 0.0]
    
    results = []
    
    for missing_et in missing_required:
        # Clone features
        sim_features = dict(base_features)
        
        # Simulate adding the evidence
        sim_features[f"has_{missing_et}"] = 1.0
        
        # Increase total evidence count
        sim_features["total_evidence_count"] += 1
        
        # Optimistically assume the new evidence is valid
        # Recalculate completeness and validity rate
        new_total_evidence = sim_features["total_evidence_count"]
        
        # completeness = required_present / max(len(required), 1)
        # we added one required
        current_required_present = int(base_features["evidence_completeness"] * max(len(required), 1))
        new_required_present = current_required_present + 1
        sim_features["evidence_completeness"] = new_required_present / max(len(required), 1)
        
        # validity_rate = valid_count / new_total
        # we assume the new doc is valid
        current_valid_count = int(base_features["evidence_validity_rate"] * base_features["total_evidence_count"])
        new_valid_count = current_valid_count + 1
        sim_features["evidence_validity_rate"] = new_valid_count / max(new_total_evidence, 1)
        
        projected_prob = predict_win_probability(model, sim_features)
        delta = projected_prob - current_prob
        
        results.append({
            "evidence_type": missing_et,
            "projected_prob": round(projected_prob, 4),
            "delta": round(delta, 4)
        })
        
    # Sort descending by delta impact
    results.sort(key=lambda x: x["delta"], reverse=True)
    return results
