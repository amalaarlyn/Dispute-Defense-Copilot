"""
Uncertainty Analyzer for Dispute Defense Copilot.

Classifies WHY a case is uncertain — the critical first step before the
Case Resolution Agent investigates. Each uncertainty source gets a severity
score (0–1) and a resolution strategy the agent should attempt.

Uncertainty Categories:
    MISSING_EVIDENCE       — key required documents not submitted
    CONFLICTING_EVIDENCE   — documents contradict each other or the transaction record
    LOW_CONFIDENCE_TAMPER  — moderate tamper signal that may be a false positive
    HIGH_CONFIDENCE_TAMPER — strong tamper signal requiring human judgment
    AMBIGUOUS_PROBABILITY  — win probability near breakeven threshold
    DEADLINE_PRESSURE      — too little time for evidence gathering
    MODEL_DISAGREEMENT     — verifier says strong but predictor says weak (or vice versa)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from schema import REASON_TO_REQUIRED_EVIDENCE, ReasonCode  # noqa: E402


class UncertaintyType(str, Enum):
    MISSING_EVIDENCE = "missing_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    LOW_CONFIDENCE_TAMPER = "low_confidence_tamper"
    HIGH_CONFIDENCE_TAMPER = "high_confidence_tamper"
    AMBIGUOUS_PROBABILITY = "ambiguous_probability"
    DEADLINE_PRESSURE = "deadline_pressure"
    MODEL_DISAGREEMENT = "model_disagreement"


class ResolutionStrategy(str, Enum):
    """What the Case Resolution Agent should attempt for each uncertainty type."""
    REQUEST_EVIDENCE = "request_evidence"           # Tell merchant which document to get
    CROSS_CHECK_DOCUMENTS = "cross_check_documents" # Compare docs against each other
    INVESTIGATE_TAMPER = "investigate_tamper"        # Deep tamper analysis
    ESCALATE_TAMPER = "escalate_tamper"              # Too risky for automation
    RECALCULATE_COST = "recalculate_cost"            # Re-examine cost tradeoff
    PRIORITIZE_ACTION = "prioritize_action"          # Time-critical: decide now
    SECONDARY_VERIFICATION = "secondary_verification"  # Run additional checks


@dataclass
class UncertaintyFinding:
    """A single identified source of uncertainty in a dispute."""
    uncertainty_type: UncertaintyType
    severity: float  # 0.0 = trivial, 1.0 = critical
    description: str
    resolution_strategy: ResolutionStrategy
    details: dict = field(default_factory=dict)
    resolvable: bool = True  # Agent believes it can resolve this


@dataclass
class UncertaintyReport:
    """Full uncertainty analysis for a dispute."""
    dispute_id: str
    findings: list[UncertaintyFinding] = field(default_factory=list)
    overall_severity: float = 0.0
    primary_uncertainty: Optional[UncertaintyType] = None
    agent_can_resolve: bool = False

    def add_finding(self, finding: UncertaintyFinding):
        self.findings.append(finding)
        self._recalculate()

    def _recalculate(self):
        if not self.findings:
            self.overall_severity = 0.0
            self.primary_uncertainty = None
            self.agent_can_resolve = False
            return
        self.overall_severity = max(f.severity for f in self.findings)
        self.primary_uncertainty = max(self.findings, key=lambda f: f.severity).uncertainty_type
        self.agent_can_resolve = any(f.resolvable for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "dispute_id": self.dispute_id,
            "findings": [
                {
                    "type": f.uncertainty_type.value,
                    "severity": round(f.severity, 3),
                    "description": f.description,
                    "resolution_strategy": f.resolution_strategy.value,
                    "resolvable": f.resolvable,
                    "details": f.details,
                }
                for f in self.findings
            ],
            "overall_severity": round(self.overall_severity, 3),
            "primary_uncertainty": self.primary_uncertainty.value if self.primary_uncertainty else None,
            "agent_can_resolve": self.agent_can_resolve,
        }


# ---------------------------------------------------------------------------
# Thresholds — tuned to produce meaningful differentiation on synthetic data
# ---------------------------------------------------------------------------

TAMPER_HIGH_THRESHOLD = 0.85    # Above this → high confidence tamper
TAMPER_LOW_THRESHOLD = 0.30     # Above this but below high → moderate tamper
AMBIGUITY_BAND = 0.05           # Matches decision_policy.AMBIGUITY_MARGIN
DEADLINE_CRITICAL_HOURS = 6.0   # Below this → deadline pressure
VALIDITY_DISAGREEMENT = 0.3     # Verifier says >0.7 valid rate but predictor says <0.4 win prob


def analyze_uncertainty(
    dispute_id: str,
    win_probability: float,
    amount: float,
    hours_remaining: float,
    verifier_results: list[dict],
    whatif_results: dict,
    reason_code: str,
    dispute_rows: list[dict],
) -> UncertaintyReport:
    """
    Analyze all sources of uncertainty for a dispute.

    Called when the Decision Policy routes a case to investigation rather
    than making a direct recommendation.
    """
    report = UncertaintyReport(dispute_id=dispute_id)

    # --- 1. Missing Evidence ---
    _check_missing_evidence(report, reason_code, dispute_rows, whatif_results, hours_remaining)

    # --- 2. Conflicting Evidence ---
    _check_conflicting_evidence(report, verifier_results, dispute_rows)

    # --- 3. Tamper Signals ---
    _check_tamper_signals(report, verifier_results, dispute_rows)

    # --- 4. Ambiguous Probability ---
    _check_ambiguous_probability(report, win_probability, amount)

    # --- 5. Deadline Pressure ---
    _check_deadline_pressure(report, hours_remaining)

    # --- 6. Model Disagreement ---
    _check_model_disagreement(report, win_probability, verifier_results)

    return report


def _check_missing_evidence(report, reason_code, dispute_rows, whatif_results, hours_remaining):
    """Check if key required evidence is missing."""
    try:
        rc = ReasonCode(reason_code)
        required = [et.value for et in REASON_TO_REQUIRED_EVIDENCE.get(rc, [])]
    except (ValueError, KeyError):
        return

    submitted_types = set(r.get("evidence_type", "") for r in dispute_rows if r.get("evidence_type"))
    missing = set(required) - submitted_types

    if not missing:
        return

    # Check if the what-if engine shows significant improvement potential
    best_improvement = 0.0
    missing_ranked = whatif_results.get("missing_evidence_ranked", [])
    if missing_ranked:
        best_improvement = missing_ranked[0].get("expected_improvement", 0.0)

    completeness = len(set(required) & submitted_types) / max(len(required), 1)

    severity = min(1.0, (1.0 - completeness) * 0.8 + (best_improvement * 2))

    # If there's time to gather evidence, this is resolvable
    has_time = hours_remaining > DEADLINE_CRITICAL_HOURS

    report.add_finding(UncertaintyFinding(
        uncertainty_type=UncertaintyType.MISSING_EVIDENCE,
        severity=round(severity, 3),
        description=(
            f"{len(missing)} of {len(required)} required evidence types are missing. "
            f"Evidence completeness: {completeness:.0%}. "
            f"Best potential improvement: {best_improvement:+.1%} if top missing evidence obtained."
        ),
        resolution_strategy=ResolutionStrategy.REQUEST_EVIDENCE,
        resolvable=has_time and best_improvement > 0.02,
        details={
            "missing_types": list(missing),
            "completeness": round(completeness, 3),
            "best_improvement": round(best_improvement, 3),
            "has_time": has_time,
        },
    ))


def _check_conflicting_evidence(report, verifier_results, dispute_rows):
    """Check if submitted evidence documents conflict with each other."""
    if not verifier_results or len(verifier_results) < 2:
        return

    # Look for cases where some documents are valid and others aren't
    valid_count = sum(1 for r in verifier_results if r.get("predicted_valid"))
    invalid_count = len(verifier_results) - valid_count

    if valid_count == 0 or invalid_count == 0:
        return  # No conflict — all agree

    # Check for specific field mismatches across documents
    all_mismatches = []
    for r in verifier_results:
        for m in r.get("field_mismatches", []):
            all_mismatches.append({
                "evidence_type": r.get("evidence_type"),
                "field": m.get("field"),
                "extracted": m.get("extracted"),
                "expected": m.get("expected"),
                "score": m.get("match_score", 0),
            })

    conflict_ratio = invalid_count / len(verifier_results)
    severity = min(1.0, conflict_ratio * 0.9)

    report.add_finding(UncertaintyFinding(
        uncertainty_type=UncertaintyType.CONFLICTING_EVIDENCE,
        severity=round(severity, 3),
        description=(
            f"{valid_count} documents verified as valid, but {invalid_count} have issues. "
            f"Found {len(all_mismatches)} field mismatch(es) across documents."
        ),
        resolution_strategy=ResolutionStrategy.CROSS_CHECK_DOCUMENTS,
        resolvable=True,  # Agent can cross-check and determine if conflicts are resolvable
        details={
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "mismatches": all_mismatches[:10],  # Cap for readability
        },
    ))


def _check_tamper_signals(report, verifier_results, dispute_rows):
    """Check tamper flag severity."""
    tamper_rows = [
        r for r in dispute_rows
        if r.get("tamper_flag_label") in (True, "True", "true", 1, "1")
    ]

    if not tamper_rows:
        return

    tamper_rate = len(tamper_rows) / max(len(dispute_rows), 1)

    # Determine if this is a high or low confidence tamper signal
    # For high confidence: many documents flagged, or critical documents flagged
    if tamper_rate >= 0.5 or len(tamper_rows) >= 3:
        report.add_finding(UncertaintyFinding(
            uncertainty_type=UncertaintyType.HIGH_CONFIDENCE_TAMPER,
            severity=min(1.0, 0.7 + tamper_rate * 0.3),
            description=(
                f"Strong tamper signal: {len(tamper_rows)} of {len(dispute_rows)} documents "
                f"flagged ({tamper_rate:.0%}). Multiple tampered documents suggest systematic issues."
            ),
            resolution_strategy=ResolutionStrategy.ESCALATE_TAMPER,
            resolvable=False,  # High confidence tamper → must escalate
            details={
                "tamper_count": len(tamper_rows),
                "total_docs": len(dispute_rows),
                "tamper_rate": round(tamper_rate, 3),
                "flagged_types": [r.get("evidence_type", "") for r in tamper_rows],
            },
        ))
    else:
        # Check if other evidence strongly supports the case despite tamper flag
        valid_non_tamper = sum(
            1 for r in verifier_results
            if r.get("predicted_valid") and r.get("evidence_type") not in
               [tr.get("evidence_type") for tr in tamper_rows]
        )

        report.add_finding(UncertaintyFinding(
            uncertainty_type=UncertaintyType.LOW_CONFIDENCE_TAMPER,
            severity=round(0.4 + tamper_rate * 0.3, 3),
            description=(
                f"Moderate tamper signal: {len(tamper_rows)} document(s) flagged, "
                f"but {valid_non_tamper} other document(s) verified as valid. "
                f"Cross-document investigation may resolve this."
            ),
            resolution_strategy=ResolutionStrategy.INVESTIGATE_TAMPER,
            resolvable=True,  # Agent can investigate
            details={
                "tamper_count": len(tamper_rows),
                "valid_non_tamper_count": valid_non_tamper,
                "tamper_rate": round(tamper_rate, 3),
                "flagged_types": [r.get("evidence_type", "") for r in tamper_rows],
            },
        ))


def _check_ambiguous_probability(report, win_probability, amount):
    """Check if win probability is in the ambiguity band around breakeven."""
    from decision_policy import _breakeven_win_prob, AMBIGUITY_MARGIN

    breakeven = _breakeven_win_prob(amount)
    distance_from_breakeven = abs(win_probability - breakeven)

    if distance_from_breakeven > AMBIGUITY_MARGIN:
        return  # Not ambiguous

    severity = max(0.3, 1.0 - (distance_from_breakeven / AMBIGUITY_MARGIN))

    report.add_finding(UncertaintyFinding(
        uncertainty_type=UncertaintyType.AMBIGUOUS_PROBABILITY,
        severity=round(severity, 3),
        description=(
            f"Win probability ({win_probability:.1%}) is within the ambiguity band "
            f"around the {breakeven:.1%} breakeven point (±{AMBIGUITY_MARGIN:.0%}). "
            f"Distance from breakeven: {distance_from_breakeven:.2%}."
        ),
        resolution_strategy=ResolutionStrategy.RECALCULATE_COST,
        resolvable=True,  # Agent can run deeper cost analysis
        details={
            "win_probability": round(win_probability, 4),
            "breakeven": round(breakeven, 4),
            "distance": round(distance_from_breakeven, 4),
            "ambiguity_margin": AMBIGUITY_MARGIN,
        },
    ))


def _check_deadline_pressure(report, hours_remaining):
    """Check if the deadline creates urgency."""
    if hours_remaining > DEADLINE_CRITICAL_HOURS:
        return

    severity = max(0.4, 1.0 - (hours_remaining / DEADLINE_CRITICAL_HOURS))

    report.add_finding(UncertaintyFinding(
        uncertainty_type=UncertaintyType.DEADLINE_PRESSURE,
        severity=round(severity, 3),
        description=(
            f"Only {hours_remaining:.0f} hours remaining to respond. "
            f"Insufficient time to gather additional evidence. "
            f"Decision must be made with current evidence state."
        ),
        resolution_strategy=ResolutionStrategy.PRIORITIZE_ACTION,
        resolvable=True,  # Agent can decide based on current evidence
        details={
            "hours_remaining": hours_remaining,
            "critical_threshold": DEADLINE_CRITICAL_HOURS,
        },
    ))


def _check_model_disagreement(report, win_probability, verifier_results):
    """Check if the verifier and predictor disagree."""
    if not verifier_results:
        return

    # Calculate average validity from verifier
    avg_validity = sum(
        r.get("confidence", 0.5) if r.get("predicted_valid") else (1 - r.get("confidence", 0.5))
        for r in verifier_results
    ) / max(len(verifier_results), 1)

    # Disagreement: evidence looks good but predictor says low probability (or vice versa)
    if avg_validity > 0.7 and win_probability < 0.4:
        report.add_finding(UncertaintyFinding(
            uncertainty_type=UncertaintyType.MODEL_DISAGREEMENT,
            severity=round(0.5 + abs(avg_validity - win_probability) * 0.5, 3),
            description=(
                f"Evidence verifier rates documents highly (avg validity: {avg_validity:.0%}), "
                f"but outcome predictor gives low win probability ({win_probability:.0%}). "
                f"Likely caused by missing required evidence types despite submitted docs being valid."
            ),
            resolution_strategy=ResolutionStrategy.SECONDARY_VERIFICATION,
            resolvable=True,
            details={
                "avg_evidence_validity": round(avg_validity, 3),
                "win_probability": round(win_probability, 4),
                "gap": round(avg_validity - win_probability, 3),
            },
        ))
    elif avg_validity < 0.4 and win_probability > 0.6:
        report.add_finding(UncertaintyFinding(
            uncertainty_type=UncertaintyType.MODEL_DISAGREEMENT,
            severity=round(0.5 + abs(win_probability - avg_validity) * 0.5, 3),
            description=(
                f"Evidence verifier rates documents poorly (avg validity: {avg_validity:.0%}), "
                f"but outcome predictor gives high win probability ({win_probability:.0%}). "
                f"May indicate the predictor is over-relying on non-evidence features."
            ),
            resolution_strategy=ResolutionStrategy.SECONDARY_VERIFICATION,
            resolvable=True,
            details={
                "avg_evidence_validity": round(avg_validity, 3),
                "win_probability": round(win_probability, 4),
                "gap": round(win_probability - avg_validity, 3),
            },
        ))
