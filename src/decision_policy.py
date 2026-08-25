"""
Decision Policy for Dispute Defense Copilot.

Conservative, defense-only decision engine that maps the win probability,
document verifier outputs, and what-if engine projections into a single
recommended action. Never auto-executes.
"""

from audit_logger import log_decision as _audit_log_decision

def evaluate_decision_policy(
    win_prob,
    evidence_completeness,
    verifier_results,
    whatif_results,
    hours_remaining
):
    """
    Apply conservative rules to determine recommendation.
    Returns: {"action": "CONTEST"|"OBTAIN"|"ESCALATE"|"ACCEPT"|"REVIEW", "reason": str}
    """
    # 1. Check for red flags -> ESCALATE
    has_tamper = any(doc.get("features", {}).get("tamper_flag", False) for doc in verifier_results)
    if has_tamper:
        result = {
            "action": "ESCALATE",
            "reason": "Tamper indicators detected on submitted evidence. Manual review required."
        }
        _audit_log_decision("N/A", result["action"], result["reason"],
                            {"win_prob": win_prob, "trigger": "tamper_detected"})
        return result
        
    has_major_mismatch = False
    for doc in verifier_results:
        for mm in doc.get("field_mismatches", []):
            if mm.get("field") == "order_id" or mm.get("match_score", 1.0) < 0.5:
                has_major_mismatch = True
    
    if has_major_mismatch:
        result = {
            "action": "ESCALATE",
            "reason": "Contradictory or severely mismatched fields detected in evidence."
        }
        _audit_log_decision("N/A", result["action"], result["reason"],
                            {"win_prob": win_prob, "trigger": "major_mismatch"})
        return result

    # 2. Check for strong case -> CONTEST
    if win_prob >= 0.70 and evidence_completeness >= 0.80:
        result = {
            "action": "CONTEST",
            "reason": f"Strong case with {win_prob:.0%} win probability and robust evidence. Recommended to contest immediately."
        }
        _audit_log_decision("N/A", result["action"], result["reason"],
                            {"win_prob": win_prob, "evidence_completeness": evidence_completeness,
                             "trigger": "strong_case"})
        return result
        
    # 3. Check for high-impact missing evidence -> OBTAIN
    if whatif_results and hours_remaining > 24:
        top_whatif = whatif_results[0]
        if top_whatif["delta"] > 0.10:
            result = {
                "action": "OBTAIN",
                "reason": f"Obtain {top_whatif['evidence_type']}. Projected win probability will rise from {win_prob:.0%} to {top_whatif['projected_prob']:.0%}."
            }
            _audit_log_decision("N/A", result["action"], result["reason"],
                                {"win_prob": win_prob, "top_whatif": top_whatif,
                                 "trigger": "high_impact_missing_evidence"})
            return result
            
    # 4. Check for inherently weak case -> ACCEPT
    # Even if we got the best missing evidence, would we win?
    best_possible_prob = win_prob
    if whatif_results:
        best_possible_prob = whatif_results[0]["projected_prob"]
        
    if best_possible_prob < 0.30:
        result = {
            "action": "ACCEPT",
            "reason": f"Weak case (max projected win probability {best_possible_prob:.0%}). Recommended to accept the dispute to avoid arbitration fees."
        }
        _audit_log_decision("N/A", result["action"], result["reason"],
                            {"win_prob": win_prob, "best_possible_prob": best_possible_prob,
                             "trigger": "weak_case"})
        return result
        
    # 5. Default fallback -> REVIEW
    result = {
        "action": "REVIEW",
        "reason": f"Moderate case ({win_prob:.0%} win probability). Consider manually reviewing the dispute and available evidence."
    }
    _audit_log_decision("N/A", result["action"], result["reason"],
                        {"win_prob": win_prob, "trigger": "default_fallback"})
    return result

def cost_weighted_evaluation(predictions, actuals, amounts, policy_actions):
    """
    Compute total cost against baselines.
    Assumptions:
    - Cost of losing a winnable case = amount
    - Cost of an unnecessary contest (losing when we contested) = 500 (fee) + amount
    - Cost of accepting = amount
    """
    total_cost_copilot = 0.0
    total_cost_contest_all = 0.0
    total_cost_accept_all = 0.0
    
    for pred_prob, actual_won, amount, action in zip(predictions, actuals, amounts, policy_actions):
        fee = 500.0
        
        # Baseline 1: Contest Everything
        if actual_won:
            total_cost_contest_all += 0.0  # we won, no loss
        else:
            total_cost_contest_all += amount + fee # lost amount + chargeback fee
            
        # Baseline 2: Accept Everything
        total_cost_accept_all += amount
        
        # Copilot
        # Assume CONTEST means we contest.
        # Assume ACCEPT means we accept.
        # Assume OBTAIN/REVIEW/ESCALATE means human decides perfectly (for evaluation simplicity, or we treat them as accept)
        # Let's say Copilot only contests if action == "CONTEST"
        if action == "CONTEST":
            if actual_won:
                total_cost_copilot += 0.0
            else:
                total_cost_copilot += amount + fee
        else:
            # We didn't contest, so we lose the amount
            total_cost_copilot += amount
            
    return {
        "cost_copilot": total_cost_copilot,
        "cost_contest_all": total_cost_contest_all,
        "cost_accept_all": total_cost_accept_all,
        "savings_vs_contest_all": total_cost_contest_all - total_cost_copilot,
        "savings_vs_accept_all": total_cost_accept_all - total_cost_copilot
    }
