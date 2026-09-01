"""
LLM Explanation & Investigation Narrative Layer — Dispute Defense Copilot.

UPGRADED from a passive explainer to an active narrator of the Case Resolution
Agent's investigation. Three modes:

  1. Standard Explanation — narrates ML results for clear-cut cases
  2. Investigation Narrative — narrates what the agent investigated and found
  3. Human Brief — creates structured guidance for escalated cases

The LLM NEVER computes a probability, a decision, or a claim of its own.
It only narrates values already produced by the pipeline modules. This keeps
hallucination risk at zero by construction.
"""

import os


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
    access / an API key. Falls back to a deterministic template so the demo
    works standalone.
    """
    if use_api:
        raise NotImplementedError(
            "Wire this to your LLM provider of choice, e.g.:\n"
            "  import anthropic\n"
            "  client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])\n"
            "  resp = client.messages.create(model=..., max_tokens=300,\n"
            "      messages=[{'role': 'user', 'content': prompt}])\n"
            "  return resp.content[0].text"
        )
    return _template_fallback(prompt)


def _template_fallback(prompt: str) -> str:
    """A deterministic, non-LLM narration used when no API is wired up —
    useful for offline demoing and for showing the fallback is honest about
    being a template, not a generated explanation."""
    return (
        "[TEMPLATE FALLBACK — replace with a real LLM call for the actual demo]\n"
        "This dispute's current evidence has been checked against the transaction "
        "record and scored by the contest outcome model; see the numbers above for "
        "the win probability, evidence validity, and the system's recommendation. "
        "Obtaining the evidence listed in the what-if analysis, if any, is the most "
        "effective way to improve the case before the deadline."
    )
