"""
EVIDRA — LLM Explanation & Case Intelligence Layer.

Three product-grade generators that turn structured pipeline output into
business-language narratives:

  1. Case Brief        — 3-4 sentence executive summary of the dispute
  2. Uncertainty Explanation — "Why is EVIDRA uncertain about this case?"
  3. Why This Decision  — structured breakdown of the recommendation rationale

IMPORTANT: The LLM NEVER computes a probability, decision, or claim.
It only narrates values already produced by the pipeline modules.
All generators work deterministically — no API key required.
If a real LLM API is available, call_llm() can be wired up for richer prose.
"""

import os
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 1. AI Case Brief
# ---------------------------------------------------------------------------

def generate_case_brief(
    dispute_id: str,
    reason_code: str,
    amount: float,
    hours_remaining: float,
    win_probability: float,
    verifier_results: list,
    whatif_results: dict,
    decision: dict,
    investigation: dict | None = None,
) -> str:
    """
    Generate a product-quality AI Case Brief in business language.

    This is the headline narrative shown on the dashboard — it should read
    like something a fintech product would display, not an ML experiment.
    """
    # Evidence summary
    total_docs = len(verifier_results)
    valid_docs = sum(1 for r in verifier_results if r.get("predicted_valid"))
    evidence_strength = _evidence_strength_label(valid_docs, total_docs)

    # Reason in plain English
    reason_label = _reason_label(reason_code)

    # Amount formatted
    amount_fmt = f"₹{amount:,.0f}"

    # Decision info
    decision_action = decision.get("decision", "")
    agent_resolved = decision.get("agent_resolved", False)
    agent_investigated = decision.get("agent_investigated", False)

    # What-if best action
    missing = whatif_results.get("missing_evidence_ranked", [])
    best_missing = missing[0] if missing else None

    # Build the brief
    lines = []

    # Sentence 1: Dispute overview
    lines.append(
        f"{amount_fmt} dispute — {reason_label}."
    )

    # Sentence 2: Evidence state
    if total_docs == 0:
        lines.append("No evidence documents have been submitted yet.")
    else:
        relevant_types = [_fmt_evidence_type(r.get("evidence_type", "")) for r in verifier_results]
        lines.append(
            f"The merchant has submitted {total_docs} evidence document{'s' if total_docs != 1 else ''} "
            f"with {evidence_strength.lower()} overall validity."
        )

    # Sentence 3: Probability + key insight
    prob_pct = f"{win_probability:.0%}"
    if best_missing and best_missing.get("expected_improvement", 0) > 0.05:
        best_type = _fmt_evidence_type(best_missing["missing_evidence_type"])
        improvement = best_missing["expected_improvement"]
        projected = win_probability + improvement
        lines.append(
            f"Current predicted contest probability is {prob_pct}. "
            f"{best_type} is the highest-impact missing evidence and could "
            f"increase the predicted probability to approximately {projected:.0%}."
        )
    else:
        lines.append(
            f"Current predicted contest probability is {prob_pct}."
        )

    # Sentence 4: Recommendation + urgency
    if decision_action == "recommend_contest":
        if agent_resolved:
            lines.append(
                f"EVIDRA investigated the uncertainty and confirmed contesting is cost-optimal. "
                f"Time remaining: {hours_remaining:.0f}h."
            )
        else:
            lines.append(
                f"Recommended action: Contest this dispute. "
                f"Time remaining: {hours_remaining:.0f}h."
            )
    elif decision_action == "recommend_accept":
        lines.append(
            f"Recommended action: Accept the chargeback. Contesting is not cost-optimal "
            f"given the current evidence and dispute amount."
        )
    elif decision_action == "recommend_obtain_evidence":
        if best_missing:
            best_type = _fmt_evidence_type(best_missing["missing_evidence_type"])
            lines.append(
                f"Recommended action: Obtain {best_type.lower()} before contesting. "
                f"Time remaining: {hours_remaining:.0f}h."
            )
        else:
            lines.append(
                f"Recommended action: Gather additional evidence before contesting. "
                f"Time remaining: {hours_remaining:.0f}h."
            )
    elif decision_action == "human_review":
        if agent_investigated:
            lines.append(
                "EVIDRA investigated but could not fully resolve the uncertainty. "
                "Human review is required."
            )
        else:
            lines.append(
                "This case requires human review before a recommendation can be made."
            )
    else:
        lines.append(f"Time remaining: {hours_remaining:.0f}h.")

    return " ".join(lines)


# ---------------------------------------------------------------------------
# 2. Uncertainty Explanation ("Why am I uncertain?")
# ---------------------------------------------------------------------------

def generate_uncertainty_explanation(
    win_probability: float,
    verifier_results: list,
    whatif_results: dict,
    investigation: dict | None = None,
) -> dict:
    """
    Generate a structured "Why am I uncertain?" explanation.

    Returns a dict with:
      - confidence_level: "HIGH" | "MEDIUM" | "LOW"
      - confirmed: list of things the system is sure about
      - concerns: list of things causing uncertainty
      - recommendation: what the system suggests
    """
    confirmed = []
    concerns = []

    # Evidence analysis
    total_docs = len(verifier_results)
    valid_docs = sum(1 for r in verifier_results if r.get("predicted_valid"))
    invalid_docs = total_docs - valid_docs

    if valid_docs > 0:
        if valid_docs == total_docs:
            confirmed.append("All submitted evidence is valid")
        else:
            confirmed.append(f"{valid_docs} of {total_docs} evidence documents are valid")

    if invalid_docs > 0:
        concerns.append(f"{invalid_docs} evidence document{'s' if invalid_docs > 1 else ''} flagged as invalid or uncertain")

    # Tamper check
    has_tamper = any(
        r.get("tamper_flag_label") in (True, "True", "true", 1, "1")
        for r in verifier_results
    )
    if has_tamper:
        concerns.append("Potential evidence tampering detected")
    else:
        if total_docs > 0:
            confirmed.append("No evidence tampering detected")

    # Missing evidence
    missing = whatif_results.get("missing_evidence_ranked", [])
    if not missing:
        confirmed.append("All required evidence types submitted")
    else:
        missing_types = [_fmt_evidence_type(m["missing_evidence_type"]) for m in missing[:3]]
        concerns.append(f"Missing evidence: {', '.join(missing_types)}")

    # Probability analysis
    if win_probability >= 0.7:
        confirmed.append("Contest probability is strong")
    elif win_probability >= 0.4:
        concerns.append("Contest probability is near the decision boundary")
    else:
        concerns.append("Contest probability is below the cost-optimal threshold")

    # Investigation findings
    if investigation:
        inv_steps = investigation.get("investigation_steps", [])
        inv_findings = investigation.get("findings_summary", [])
        if inv_steps:
            confirmed.append(f"AI performed {len(inv_steps)} investigation check{'s' if len(inv_steps) > 1 else ''}")

    # Confidence level
    if len(concerns) == 0:
        confidence = "HIGH"
    elif len(concerns) <= 1 and len(confirmed) >= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW" if len(concerns) >= 3 else "MEDIUM"

    # Recommendation
    if confidence == "HIGH":
        recommendation = "Proceed with the recommended action."
    elif missing and missing[0].get("expected_improvement", 0) > 0.05:
        best = _fmt_evidence_type(missing[0]["missing_evidence_type"])
        recommendation = f"Obtain {best.lower()} before contesting."
    elif has_tamper:
        recommendation = "Verify evidence authenticity before proceeding."
    else:
        recommendation = "Review the evidence and investigation findings before deciding."

    return {
        "confidence_level": confidence,
        "confirmed": confirmed,
        "concerns": concerns,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# 3. Why This Decision
# ---------------------------------------------------------------------------

def generate_why_decision(
    win_probability: float,
    amount: float,
    hours_remaining: float,
    verifier_results: list,
    whatif_results: dict,
    decision: dict,
) -> dict:
    """
    Generate structured "Why this decision?" breakdown.

    Returns metrics and a plain-language conclusion for the UI.
    """
    total_docs = len(verifier_results)
    valid_docs = sum(1 for r in verifier_results if r.get("predicted_valid"))

    # Evidence strength
    strength = _evidence_strength_label(valid_docs, total_docs)

    # Completeness
    missing = whatif_results.get("missing_evidence_ranked", [])
    required_total = total_docs + len(missing)
    completeness = f"{total_docs}/{required_total}" if required_total > 0 else "N/A"

    # Expected loss
    escalation_fee = 500.0
    expected_loss_contest = (1 - win_probability) * (amount + escalation_fee)
    expected_loss_accept = amount

    # Time assessment
    if hours_remaining > 24:
        time_label = "Comfortable"
    elif hours_remaining > 6:
        time_label = "Moderate"
    else:
        time_label = "Urgent"

    # Conclusion
    decision_action = decision.get("decision", "")
    if decision_action == "recommend_contest":
        conclusion = (
            f"The case is above the cost-adjusted contest threshold. "
            f"Expected loss if contesting (₹{expected_loss_contest:,.0f}) is lower than "
            f"accepting (₹{expected_loss_accept:,.0f})."
        )
    elif decision_action == "recommend_accept":
        conclusion = (
            f"The case is below the cost-adjusted contest threshold. "
            f"Expected loss if contesting (₹{expected_loss_contest:,.0f}) exceeds "
            f"accepting (₹{expected_loss_accept:,.0f})."
        )
    elif decision_action == "recommend_obtain_evidence":
        conclusion = (
            f"Current evidence is insufficient to contest cost-effectively, "
            f"but obtaining missing evidence could change the outcome."
        )
    elif decision_action == "human_review":
        conclusion = (
            f"The case has unresolved uncertainty that requires human judgment."
        )
    else:
        conclusion = "Decision analysis in progress."

    return {
        "evidence_strength": strength,
        "evidence_completeness": completeness,
        "contest_probability": f"{win_probability:.0%}",
        "expected_loss_contest": f"₹{expected_loss_contest:,.0f}",
        "expected_loss_accept": f"₹{expected_loss_accept:,.0f}",
        "time_remaining": f"{hours_remaining:.0f}h",
        "time_urgency": time_label,
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _evidence_strength_label(valid_count: int, total_count: int) -> str:
    """Convert evidence validity ratio to a business-language label."""
    if total_count == 0:
        return "No Evidence"
    ratio = valid_count / total_count
    if ratio >= 0.9:
        return "Strong"
    elif ratio >= 0.7:
        return "Moderate"
    elif ratio >= 0.5:
        return "Weak"
    else:
        return "Insufficient"


def _reason_label(reason_code: str) -> str:
    """Convert reason_code to a plain-English label."""
    labels = {
        "goods_not_received": "Goods/Services Not Received",
        "not_as_described": "Product Not As Described",
        "fraudulent": "Unauthorized/Fraudulent Transaction",
        "duplicate": "Duplicate Transaction",
        "subscription_canceled": "Subscription Canceled",
        "credit_not_processed": "Credit/Refund Not Processed",
    }
    return labels.get(reason_code, reason_code.replace("_", " ").title() if reason_code else "Unknown")


def _fmt_evidence_type(evidence_type: str) -> str:
    """Format an evidence type for display."""
    return evidence_type.replace("_", " ").title() if evidence_type else "Unknown"


# ---------------------------------------------------------------------------
# LLM API hook (preserved for future use)
# ---------------------------------------------------------------------------

def build_explanation_prompt(dispute_summary: dict) -> str:
    """
    Build the prompt for a standard case explanation.

    dispute_summary must contain only values already computed elsewhere:
    dispute_id, reason_code, amount, hours_remaining, evidence_status
    (list of {type, valid, confidence}), win_prob, decision, decision_reason,
    whatif_ranked (list of {missing_evidence_type, expected_improvement}).
    """
    evidence_lines = "\n".join(
        f"  - {e['type']}: {'VALID' if e['valid'] else 'INVALID/UNCERTAIN'} "
        f"(confidence {e['confidence']:.0%})"
        for e in dispute_summary["evidence_status"]
    )
    whatif_lines = "\n".join(
        f"  - Obtaining {w['missing_evidence_type']} could improve win probability by "
        f"{w['expected_improvement']:+.0%}"
        for w in dispute_summary.get("whatif_ranked", [])[:3]
    )

    prompt = f"""You are explaining a chargeback dispute analysis to a merchant. \
Use ONLY the facts given below. Do not estimate, guess, or add any number, \
probability, or claim that is not explicitly provided. Do not speculate about \
whether the customer is being honest. Write 3-4 plain sentences a non-technical \
merchant would understand.

Dispute: {dispute_summary['dispute_id']}
Reason: {dispute_summary['reason_code']}
Amount: Rs.{dispute_summary['amount']:,.0f}
Hours remaining to respond: {dispute_summary['hours_remaining']:.0f}

Evidence status:
{evidence_lines}

Model-predicted contest win probability: {dispute_summary['win_prob']:.0%}

What-if analysis (if evidence were added):
{whatif_lines if whatif_lines else "  (no missing evidence, or no time remaining to obtain more)"}

System recommendation: {dispute_summary['decision']}
Reason for recommendation: {dispute_summary['decision_reason']}

Write the explanation now."""
    return prompt


def build_investigation_narrative(investigation: dict) -> str:
    """
    Build a narrative of what the AI Case Agent investigated and found.

    This is shown on the dashboard when a case was sent to the agent.
    All facts come from the investigation report — no invented claims.
    """
    if not investigation:
        return ""

    status = investigation.get("status", "unknown")
    steps = investigation.get("investigation_steps", [])
    findings = investigation.get("findings_summary", [])
    recommendation = investigation.get("final_recommendation", "")
    reason = investigation.get("final_reason", "")

    lines = []

    # Header
    if status == "resolved":
        lines.append("🤖 **AI Case Agent — Investigation Complete (Resolved)**\n")
    else:
        lines.append("🤖 **AI Case Agent — Investigation Complete (Escalated to Human)**\n")

    # Uncertainty analysis
    uncertainty = investigation.get("uncertainty_analysis", {})
    primary = uncertainty.get("primary_uncertainty", "")
    if primary:
        lines.append(f"**Primary uncertainty:** {primary.replace('_', ' ').title()}")

    # Investigation steps
    if steps:
        lines.append("\n**Investigation steps performed:**")
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step.get('description', 'Unknown step')}")
            lines.append(f"     → {step.get('conclusion', '')}")

    # Final findings
    if findings:
        lines.append("\n**Key findings:**")
        for finding in findings:
            lines.append(f"  • {finding}")

    # Recommendation
    if recommendation:
        action_label = recommendation.replace("recommend_", "").replace("_", " ").title()
        lines.append(f"\n**Recommendation:** {action_label}")
        if reason:
            lines.append(f"**Reasoning:** {reason}")

    return "\n".join(lines)


def build_human_brief_narrative(human_brief: dict) -> str:
    """
    Build a narrative for the human reviewer when the agent escalates.

    Shows: what was already investigated, what the human should focus on,
    and estimated time saved.
    """
    if not human_brief:
        return ""

    lines = []
    lines.append("## 📋 AI Investigation Brief for Human Reviewer\n")
    lines.append(f"**Summary:** {human_brief.get('summary', '')}\n")

    # Already investigated
    already = human_brief.get("already_investigated", [])
    if already:
        lines.append("### ✅ Already Investigated by AI")
        for item in already:
            lines.append(f"  • **{item.get('check', '')}**")
            lines.append(f"    Result: {item.get('result', '')}")

    # What the human should focus on
    focus = human_brief.get("human_focus_areas", [])
    if focus:
        lines.append("\n### 🎯 Human Should Investigate")
        for area in focus:
            severity_label = "🔴" if area.get("severity", 0) > 0.7 else "🟡" if area.get("severity", 0) > 0.4 else "🟢"
            lines.append(f"  {severity_label} **{area.get('area', '').replace('_', ' ').title()}**")
            lines.append(f"    {area.get('description', '')}")
            lines.append(f"    *Suggested action:* {area.get('suggested_action', '')}")

    # Time saved
    time_saved = human_brief.get("time_saved_estimate", "")
    if time_saved:
        lines.append(f"\n⏱️ *{time_saved}*")

    return "\n".join(lines)


def call_llm(prompt: str, use_api: bool = False) -> str:
    """
    Set use_api=True and fill in a real client call once you have network
    access / an API key. Falls back to the deterministic generators.
    """
    if use_api:
        raise NotImplementedError(
            "Wire this to your LLM provider of choice, e.g.:\n"
            "  import google.generativeai as genai\n"
            "  genai.configure(api_key=os.environ['GEMINI_API_KEY'])\n"
            "  model = genai.GenerativeModel('gemini-pro')\n"
            "  response = model.generate_content(prompt)\n"
            "  return response.text"
        )
    return ""
