"""
AI Case Resolution Agent for Dispute Defense Copilot.

The centerpiece module: a tool-using AI agent that investigates uncertainty
BEFORE escalating to human review. This is the key differentiator:

    Before: Ambiguous → Human Review
    After:  Ambiguous → AI Investigates → Resolved? → Auto-Recommend
                                        → Unresolved? → Human Review (with AI brief)

The agent does NOT freely reason — it follows a structured investigation
protocol using only the safe, read-only tools defined in agent_tools.py.
It cannot modify state, submit documents, or move money.

Architecture:
    1. Uncertainty Analyzer identifies WHY the case is uncertain
    2. Agent selects investigation tools based on uncertainty type
    3. Agent runs tools and collects findings
    4. Agent determines if ambiguity is resolved
    5. If resolved → returns automated recommendation
    6. If not → returns structured human brief

The agent is deliberately conservative: when in doubt, escalate.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))

from uncertainty_analyzer import (
    analyze_uncertainty,
    UncertaintyType,
    UncertaintyReport,
    ResolutionStrategy,
)
from agent_tools import (
    check_document_consistency,
    analyze_tamper_signal,
    get_deadline_urgency,
    calculate_cost_tradeoff,
    search_similar_cases,
)
from audit_logger import get_logger, log_event, EventType

_logger = get_logger(__name__)


@dataclass
class InvestigationStep:
    """A single step the agent took during investigation."""
    tool_name: str
    description: str
    result: dict
    conclusion: str  # What the agent concluded from this tool call


@dataclass
class InvestigationReport:
    """Complete investigation report from the Case Resolution Agent."""
    dispute_id: str
    status: str  # "resolved" | "escalated"
    uncertainty_report: dict  # From UncertaintyAnalyzer
    steps: list[InvestigationStep] = field(default_factory=list)
    findings_summary: list[str] = field(default_factory=list)
    final_recommendation: Optional[str] = None  # "recommend_contest" | "recommend_accept" | etc.
    final_reason: Optional[str] = None
    confidence: float = 0.0
    human_brief: Optional[dict] = None  # Structured brief if escalated

    def add_step(self, step: InvestigationStep):
        self.steps.append(step)

    def add_finding(self, finding: str):
        self.findings_summary.append(finding)

    def to_dict(self) -> dict:
        return {
            "dispute_id": self.dispute_id,
            "status": self.status,
            "uncertainty_analysis": self.uncertainty_report,
            "investigation_steps": [
                {
                    "tool": s.tool_name,
                    "description": s.description,
                    "result": s.result,
                    "conclusion": s.conclusion,
                }
                for s in self.steps
            ],
            "findings_summary": self.findings_summary,
            "final_recommendation": self.final_recommendation,
            "final_reason": self.final_reason,
            "confidence": round(self.confidence, 3),
            "human_brief": self.human_brief,
        }


class CaseResolutionAgent:
    """
    AI Case Resolution Agent.

    Investigates ambiguous disputes using structured tools before escalating
    to human review. Follows a deterministic investigation protocol based
    on the identified uncertainty types.
    """

    def __init__(self):
        self._logger = get_logger("case_agent")

    def investigate(
        self,
        dispute_id: str,
        win_probability: float,
        amount: float,
        hours_remaining: float,
        reason_code: str,
        verifier_results: list[dict],
        whatif_results: dict,
        dispute_rows: list[dict],
        original_decision: str,
    ) -> InvestigationReport:
        """
        Run a full investigation on an ambiguous dispute.

        Parameters
        ----------
        dispute_id : str
        win_probability : float
            From the Outcome Predictor
        amount : float
        hours_remaining : float
        reason_code : str
        verifier_results : list[dict]
            From the Evidence Verifier
        whatif_results : dict
            From the What-If Engine
        dispute_rows : list[dict]
            Raw evidence document rows
        original_decision : str
            The original decision that triggered investigation

        Returns
        -------
        InvestigationReport
        """
        self._logger.info(
            "Agent investigating dispute %s (original: %s, P(win)=%.2f)",
            dispute_id, original_decision, win_probability,
        )

        # Step 1: Analyze uncertainty sources
        uncertainty = analyze_uncertainty(
            dispute_id=dispute_id,
            win_probability=win_probability,
            amount=amount,
            hours_remaining=hours_remaining,
            verifier_results=verifier_results,
            whatif_results=whatif_results,
            reason_code=reason_code,
            dispute_rows=dispute_rows,
        )

        report = InvestigationReport(
            dispute_id=dispute_id,
            status="investigating",
            uncertainty_report=uncertainty.to_dict(),
        )

        if not uncertainty.findings:
            # No specific uncertainty identified — shouldn't happen but handle gracefully
            report.status = "resolved"
            report.final_recommendation = "human_review"
            report.final_reason = "No specific uncertainty identified but case was flagged for review."
            report.confidence = 0.3
            return report

        # Step 2: Run targeted investigation based on uncertainty types
        for finding in sorted(uncertainty.findings, key=lambda f: f.severity, reverse=True):
            self._investigate_finding(report, finding, dispute_rows, verifier_results,
                                       win_probability, amount, hours_remaining, reason_code)

        # Step 3: Synthesize findings into a final recommendation
        self._synthesize(report, uncertainty, win_probability, amount, hours_remaining)

        # Log the investigation
        log_event("AGENT_INVESTIGATION", report.to_dict(), dispute_id=dispute_id)

        self._logger.info(
            "Agent completed investigation for %s — status=%s, recommendation=%s",
            dispute_id, report.status, report.final_recommendation,
        )

        return report

    def _investigate_finding(
        self,
        report: InvestigationReport,
        finding,
        dispute_rows: list[dict],
        verifier_results: list[dict],
        win_probability: float,
        amount: float,
        hours_remaining: float,
        reason_code: str,
    ):
        """Run the appropriate investigation tool for a specific uncertainty finding."""
        strategy = finding.resolution_strategy

        if strategy == ResolutionStrategy.CROSS_CHECK_DOCUMENTS:
            result = check_document_consistency(dispute_rows)
            conclusion = self._interpret_consistency(result)
            report.add_step(InvestigationStep(
                tool_name="check_document_consistency",
                description="Cross-validating all evidence documents against each other",
                result=result,
                conclusion=conclusion,
            ))
            report.add_finding(conclusion)

        elif strategy == ResolutionStrategy.INVESTIGATE_TAMPER:
            result = analyze_tamper_signal(dispute_rows, verifier_results)
            conclusion = self._interpret_tamper(result)
            report.add_step(InvestigationStep(
                tool_name="analyze_tamper_signal",
                description="Deep investigation of tamper flags for false positive detection",
                result=result,
                conclusion=conclusion,
            ))
            report.add_finding(conclusion)

        elif strategy == ResolutionStrategy.ESCALATE_TAMPER:
            # High confidence tamper — still investigate but expect escalation
            result = analyze_tamper_signal(dispute_rows, verifier_results)
            conclusion = (
                "High-confidence tamper signal confirmed. "
                f"Tamper rate: {result.get('tamper_count', 0)}/{result.get('tamper_count', 0) + result.get('clean_count', 0)} documents. "
                "This requires human judgment."
            )
            report.add_step(InvestigationStep(
                tool_name="analyze_tamper_signal",
                description="Investigating high-confidence tamper signal",
                result=result,
                conclusion=conclusion,
            ))
            report.add_finding(conclusion)

        elif strategy == ResolutionStrategy.RECALCULATE_COST:
            result = calculate_cost_tradeoff(win_probability, amount, hours_remaining)
            conclusion = self._interpret_cost(result)
            report.add_step(InvestigationStep(
                tool_name="calculate_cost_tradeoff",
                description="Detailed expected-value analysis of contest vs accept",
                result=result,
                conclusion=conclusion,
            ))
            report.add_finding(conclusion)

        elif strategy == ResolutionStrategy.REQUEST_EVIDENCE:
            # Check deadline first
            urgency = get_deadline_urgency(hours_remaining)
            report.add_step(InvestigationStep(
                tool_name="get_deadline_urgency",
                description="Assessing time available for evidence gathering",
                result=urgency,
                conclusion=f"Urgency: {urgency['urgency_band']}. {urgency['guidance']}",
            ))

            # Then check what evidence would help most (from whatif data in finding)
            missing_types = finding.details.get("missing_types", [])
            best_improvement = finding.details.get("best_improvement", 0)
            conclusion = (
                f"Missing evidence: {', '.join(missing_types)}. "
                f"Best potential improvement: {best_improvement:+.1%}. "
                f"{'Time available to gather evidence.' if urgency['can_gather_evidence'] else 'Deadline too tight for evidence gathering.'}"
            )
            report.add_finding(conclusion)

        elif strategy == ResolutionStrategy.PRIORITIZE_ACTION:
            urgency = get_deadline_urgency(hours_remaining)
            cost = calculate_cost_tradeoff(win_probability, amount, hours_remaining)
            conclusion = (
                f"Deadline pressure ({hours_remaining:.0f}h remaining). "
                f"Based on current evidence: {cost['ev_optimal_action']} is cost-optimal. "
                f"Expected loss if contest: ₹{cost['expected_loss_contest']:,.0f}, "
                f"if accept: ₹{cost['expected_loss_accept']:,.0f}."
            )
            report.add_step(InvestigationStep(
                tool_name="get_deadline_urgency + calculate_cost_tradeoff",
                description="Time-critical assessment with cost analysis",
                result={"urgency": urgency, "cost": cost},
                conclusion=conclusion,
            ))
            report.add_finding(conclusion)

        elif strategy == ResolutionStrategy.SECONDARY_VERIFICATION:
            # Cross-check + similar cases
            consistency = check_document_consistency(dispute_rows)
            submitted_types = set(r.get("evidence_type", "") for r in dispute_rows if r.get("evidence_type"))
            similar = search_similar_cases(reason_code, submitted_types, win_probability)

            conclusion = (
                f"Document consistency: {'consistent' if consistency['consistent'] else 'inconsistencies found'}. "
                f"Similar cases: {similar.get('message', 'N/A')}"
            )
            report.add_step(InvestigationStep(
                tool_name="check_document_consistency + search_similar_cases",
                description="Secondary verification through cross-checks and historical comparison",
                result={"consistency": consistency, "similar_cases": similar},
                conclusion=conclusion,
            ))
            report.add_finding(conclusion)

    def _interpret_consistency(self, result: dict) -> str:
        """Interpret document consistency check results."""
        if result.get("consistent"):
            return (
                "All evidence documents are internally consistent. "
                "Order IDs, customer names, dates, and addresses match across documents."
            )
        inconsistent = result.get("inconsistent_fields", [])
        details = []
        for field_name in inconsistent:
            field_data = result.get("field_consistency", {}).get(field_name, {})
            details.append(
                f"{field_name} (similarity: {field_data.get('score', 0):.0%}, "
                f"{field_data.get('unique_values', 0)} unique values)"
            )
        return (
            f"Cross-document inconsistencies found in: {', '.join(details)}. "
            f"This may explain the model's uncertainty."
        )

    def _interpret_tamper(self, result: dict) -> str:
        """Interpret tamper investigation results."""
        conclusion = result.get("conclusion", "unknown")
        if conclusion == "likely_false_positive":
            return (
                "Tamper signal is likely a FALSE POSITIVE. "
                f"All {result.get('tamper_count', 0)} flagged document(s) have perfect field matches, "
                f"and {result.get('clean_docs_valid', 0)} clean documents corroborate the transaction. "
                "Recommend proceeding with contest."
            )
        elif conclusion == "possibly_false_positive":
            return (
                "Tamper signal is MODERATE but unsupported by cross-document inconsistencies. "
                f"{result.get('tamper_with_matching_fields', 0)}/{result.get('tamper_count', 0)} "
                f"flagged documents have matching fields. "
                "Recommend contest with secondary verification flag."
            )
        else:
            return (
                "Tamper signal is a GENUINE CONCERN. "
                f"Field-level mismatches found in flagged documents. "
                "Human review is recommended."
            )

    def _interpret_cost(self, result: dict) -> str:
        """Interpret cost tradeoff analysis."""
        optimal = result.get("ev_optimal_action", "marginal")
        clarity = result.get("decision_clarity", 0)

        if optimal == "contest" and clarity > 0.5:
            return (
                f"Cost analysis RESOLVES the ambiguity: contesting is clearly cost-optimal. "
                f"Expected loss if contest: ₹{result['expected_loss_contest']:,.0f} vs "
                f"accept: ₹{result['expected_loss_accept']:,.0f}. "
                f"Decision clarity: {clarity:.0%}."
            )
        elif optimal == "accept" and clarity > 0.5:
            return (
                f"Cost analysis RESOLVES the ambiguity: accepting is cost-optimal. "
                f"Expected loss if contest: ₹{result['expected_loss_contest']:,.0f} vs "
                f"accept: ₹{result['expected_loss_accept']:,.0f}. "
                f"Decision clarity: {clarity:.0%}."
            )
        else:
            return (
                f"Cost analysis shows the decision is TRULY MARGINAL. "
                f"Expected loss if contest: ₹{result['expected_loss_contest']:,.0f} vs "
                f"accept: ₹{result['expected_loss_accept']:,.0f}. "
                f"Decision clarity: {clarity:.0%}."
            )

    def _synthesize(
        self,
        report: InvestigationReport,
        uncertainty: UncertaintyReport,
        win_probability: float,
        amount: float,
        hours_remaining: float,
    ):
        """
        Synthesize all investigation findings into a final recommendation.

        This is the critical decision point: can the agent resolve the ambiguity,
        or must it escalate to a human?
        """
        # Collect resolution signals from investigation steps
        resolved_signals = []
        unresolved_signals = []

        for step in report.steps:
            result = step.result

            # Tamper investigation outcome
            if step.tool_name == "analyze_tamper_signal":
                conclusion = result.get("conclusion", "")
                if conclusion in ("likely_false_positive", "possibly_false_positive"):
                    resolved_signals.append(("tamper_cleared", result.get("confidence", 0.5)))
                elif conclusion == "genuine_concern":
                    unresolved_signals.append(("tamper_confirmed", 0.8))

            # Document consistency
            elif step.tool_name == "check_document_consistency":
                if result.get("consistent"):
                    resolved_signals.append(("docs_consistent", 0.7))
                else:
                    unresolved_signals.append(("docs_inconsistent", 0.6))

            # Cost tradeoff
            elif step.tool_name == "calculate_cost_tradeoff":
                optimal = result.get("ev_optimal_action", "marginal")
                clarity = result.get("decision_clarity", 0)
                if optimal != "marginal" and clarity > 0.4:
                    resolved_signals.append(("cost_clear", clarity))
                else:
                    unresolved_signals.append(("cost_marginal", 1.0 - clarity))

            # Combined tools
            elif "calculate_cost_tradeoff" in step.tool_name:
                # Extract from nested result
                cost = result.get("cost", result)
                if isinstance(cost, dict):
                    optimal = cost.get("ev_optimal_action", "marginal")
                    clarity = cost.get("decision_clarity", 0)
                    if optimal != "marginal" and clarity > 0.4:
                        resolved_signals.append(("deadline_cost_clear", clarity))

        # Decision: can we resolve this?
        total_resolved_weight = sum(w for _, w in resolved_signals)
        total_unresolved_weight = sum(w for _, w in unresolved_signals)

        # Check for absolute blockers
        has_high_tamper = any(
            f.uncertainty_type == UncertaintyType.HIGH_CONFIDENCE_TAMPER
            for f in uncertainty.findings
        )

        if has_high_tamper and not any(s[0] == "tamper_cleared" for s in resolved_signals):
            # High tamper that wasn't cleared → must escalate
            report.status = "escalated"
            report.final_recommendation = "human_review"
            report.confidence = 0.85
            report.final_reason = (
                "High-confidence tamper signal detected that could not be resolved "
                "through cross-document analysis. Human judgment required."
            )
            report.human_brief = self._build_human_brief(report, uncertainty, win_probability, amount)
            return

        # Weighted resolution decision
        if total_resolved_weight > total_unresolved_weight and total_resolved_weight > 0.5:
            # Agent can resolve this!
            report.status = "resolved"
            report.confidence = min(0.9, 0.5 + total_resolved_weight * 0.3)

            # Determine what to recommend based on investigation
            cost_step = next(
                (s for s in report.steps if "cost_tradeoff" in s.tool_name),
                None,
            )
            if cost_step:
                cost_result = cost_step.result
                if isinstance(cost_result, dict) and "cost" in cost_result:
                    cost_result = cost_result["cost"]
                optimal = cost_result.get("ev_optimal_action", "contest")
            else:
                # Default based on win probability
                from decision_policy import _breakeven_win_prob
                breakeven = _breakeven_win_prob(amount)
                optimal = "contest" if win_probability >= breakeven else "accept"

            # Check if we should recommend obtaining evidence instead
            has_missing = any(
                f.uncertainty_type == UncertaintyType.MISSING_EVIDENCE
                for f in uncertainty.findings
            )
            can_gather = hours_remaining > 6

            if has_missing and can_gather and optimal != "contest":
                report.final_recommendation = "recommend_obtain_evidence"
                report.final_reason = (
                    "AI investigation found that missing evidence is the primary source of uncertainty. "
                    "Time is available to gather the required documents."
                )
            elif optimal == "contest":
                report.final_recommendation = "recommend_contest"
                report.final_reason = (
                    "AI investigation resolved the ambiguity. "
                    "Cost analysis confirms contesting is optimal, and no blocking issues were found."
                )
            else:
                report.final_recommendation = "recommend_accept"
                report.final_reason = (
                    "AI investigation confirmed that the evidence is insufficient to win "
                    "and contesting is not cost-optimal for this dispute."
                )
        else:
            # Cannot resolve → escalate with structured brief
            report.status = "escalated"
            report.final_recommendation = "human_review"
            report.confidence = 0.4 + total_unresolved_weight * 0.2
            report.final_reason = (
                "AI investigation could not fully resolve the uncertainty. "
                f"Resolved: {len(resolved_signals)} signals, Unresolved: {len(unresolved_signals)} signals. "
                "Escalating to human review with investigation brief."
            )
            report.human_brief = self._build_human_brief(report, uncertainty, win_probability, amount)

    def _build_human_brief(
        self,
        report: InvestigationReport,
        uncertainty: UncertaintyReport,
        win_probability: float,
        amount: float,
    ) -> dict:
        """
        Build a structured brief for the human reviewer.

        This is the key UX innovation: humans don't get a raw problem,
        they get a PARTIALLY INVESTIGATED problem with clear guidance
        on what still needs their judgment.
        """
        # What the AI already checked
        already_investigated = [
            {
                "check": step.description,
                "result": step.conclusion,
                "tool": step.tool_name,
            }
            for step in report.steps
        ]

        # What the human should focus on
        focus_areas = []
        for finding in uncertainty.findings:
            if not finding.resolvable:
                focus_areas.append({
                    "area": finding.uncertainty_type.value,
                    "description": finding.description,
                    "severity": finding.severity,
                    "suggested_action": self._human_action_suggestion(finding),
                })

        # If no unresolvable findings, add generic guidance
        if not focus_areas:
            focus_areas.append({
                "area": "general_review",
                "description": "The AI could not confidently resolve this case. Please review the investigation findings.",
                "severity": 0.5,
                "suggested_action": "Review the evidence documents and investigation findings, then make a judgment call.",
            })

        return {
            "summary": (
                f"Dispute for ₹{amount:,.0f} with {win_probability:.0%} predicted win probability. "
                f"AI investigated {len(report.steps)} aspect(s) but could not fully resolve the uncertainty."
            ),
            "already_investigated": already_investigated,
            "human_focus_areas": focus_areas,
            "ai_findings": report.findings_summary,
            "time_saved_estimate": f"~{len(report.steps) * 3} minutes of investigation already completed by AI",
        }

    def _human_action_suggestion(self, finding) -> str:
        """Suggest what the human should do for unresolvable findings."""
        suggestions = {
            UncertaintyType.HIGH_CONFIDENCE_TAMPER: (
                "Examine the flagged documents manually. Confirm whether the "
                "tamper indicator represents actual document manipulation."
            ),
            UncertaintyType.CONFLICTING_EVIDENCE: (
                "Review the specific field mismatches identified. Determine if "
                "the inconsistencies are data entry errors or genuine conflicts."
            ),
            UncertaintyType.MODEL_DISAGREEMENT: (
                "The ML models disagree. Check if additional context (business "
                "relationship, prior disputes) explains the discrepancy."
            ),
        }
        return suggestions.get(
            finding.uncertainty_type,
            "Review the investigation findings and apply business judgment.",
        )
