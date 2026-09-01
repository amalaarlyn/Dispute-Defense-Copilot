"""
Agent Tools — Safe, read-only investigation tools for the Case Resolution Agent.

The AI agent can ONLY call these tools. Each tool:
  - Takes structured input (no free-form text)
  - Returns structured output (dict)
  - Cannot modify state, submit documents, or move money
  - Is logged to the audit trail

This constraint keeps the agent "defense-only" — it can READ, ANALYZE,
and RECOMMEND, but never ACT on the merchant's behalf.
"""

from __future__ import annotations

import os
import sys
import csv
from difflib import SequenceMatcher
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from schema import REASON_TO_REQUIRED_EVIDENCE, ReasonCode  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'synthetic_disputes.csv')


# ---------------------------------------------------------------------------
# Tool 1: Document Consistency Check
# ---------------------------------------------------------------------------

def check_document_consistency(dispute_rows: list[dict]) -> dict:
    """
    Cross-validate all evidence documents in a dispute against each other.

    Checks:
    - Do all documents reference the same order ID?
    - Do customer names match across documents?
    - Are dates consistent?
    - Are addresses consistent?

    Returns a consistency report with per-field analysis.
    """
    if not dispute_rows or len(dispute_rows) < 2:
        return {
            "tool": "check_document_consistency",
            "consistent": True,
            "single_document": True,
            "message": "Only one document submitted — no cross-document check possible.",
            "field_consistency": {},
        }

    # Collect extracted fields from each document
    order_ids = []
    names = []
    dates = []
    addresses = []

    for row in dispute_rows:
        if row.get("evidence_type"):
            order_ids.append(row.get("extracted_order_id", ""))
            names.append(row.get("extracted_customer_name", ""))
            dates.append(row.get("extracted_date", ""))
            addresses.append(row.get("extracted_address", ""))

    def _consistency_score(values):
        """Pairwise fuzzy similarity average."""
        if len(values) < 2:
            return 1.0
        scores = []
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                scores.append(
                    SequenceMatcher(None, str(values[i]).lower(), str(values[j]).lower()).ratio()
                )
        return sum(scores) / len(scores) if scores else 1.0

    field_consistency = {
        "order_id": {
            "score": round(_consistency_score(order_ids), 3),
            "unique_values": len(set(order_ids)),
            "consistent": _consistency_score(order_ids) > 0.95,
        },
        "customer_name": {
            "score": round(_consistency_score(names), 3),
            "unique_values": len(set(names)),
            "consistent": _consistency_score(names) > 0.85,
        },
        "date": {
            "score": round(_consistency_score(dates), 3),
            "unique_values": len(set(dates)),
            "consistent": _consistency_score(dates) > 0.9,
        },
        "address": {
            "score": round(_consistency_score(addresses), 3),
            "unique_values": len(set(addresses)),
            "consistent": _consistency_score(addresses) > 0.8,
        },
    }

    all_consistent = all(f["consistent"] for f in field_consistency.values())
    inconsistent_fields = [k for k, v in field_consistency.items() if not v["consistent"]]

    return {
        "tool": "check_document_consistency",
        "consistent": all_consistent,
        "single_document": False,
        "documents_checked": len(dispute_rows),
        "field_consistency": field_consistency,
        "inconsistent_fields": inconsistent_fields,
        "message": (
            "All documents are internally consistent."
            if all_consistent
            else f"Inconsistencies found in: {', '.join(inconsistent_fields)}."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 2: Tamper Signal Investigation
# ---------------------------------------------------------------------------

def analyze_tamper_signal(dispute_rows: list[dict], verifier_results: list[dict]) -> dict:
    """
    Deep investigation of tamper flags.

    Checks:
    - How many documents are tamper-flagged?
    - Do the flagged documents still have correct field matches?
    - Do non-flagged documents corroborate the transaction?
    - Is the tamper likely a false positive?

    A tamper flag + perfect field matches across all documents = likely false positive.
    A tamper flag + field mismatches + inconsistencies = genuine concern.
    """
    tamper_docs = []
    clean_docs = []

    for row in dispute_rows:
        is_tamper = row.get("tamper_flag_label") in (True, "True", "true", 1, "1")
        doc_info = {
            "evidence_type": row.get("evidence_type", ""),
            "order_id_matches": row.get("extracted_order_id", "") == row.get("true_order_id", ""),
            "name_matches": SequenceMatcher(
                None,
                str(row.get("extracted_customer_name", "")).lower(),
                str(row.get("true_customer_name", "")).lower()
            ).ratio() > 0.85,
            "date_matches": row.get("extracted_date", "") == row.get("true_date", ""),
            "address_matches": SequenceMatcher(
                None,
                str(row.get("extracted_address", "")).lower(),
                str(row.get("true_address", "")).lower()
            ).ratio() > 0.8,
        }
        doc_info["all_fields_match"] = all([
            doc_info["order_id_matches"], doc_info["name_matches"],
            doc_info["date_matches"], doc_info["address_matches"],
        ])

        if is_tamper:
            tamper_docs.append(doc_info)
        else:
            clean_docs.append(doc_info)

    if not tamper_docs:
        return {
            "tool": "analyze_tamper_signal",
            "tamper_found": False,
            "conclusion": "no_tamper",
            "message": "No tamper flags detected in any documents.",
        }

    # Key question: does the tamper flag contradict the field-level evidence?
    tamper_with_matching_fields = sum(1 for d in tamper_docs if d["all_fields_match"])
    clean_docs_valid = sum(1 for d in clean_docs if d["all_fields_match"])

    # False positive indicators
    false_positive_signals = 0
    if tamper_with_matching_fields == len(tamper_docs):
        false_positive_signals += 2  # All tampered docs have perfect field matches
    if clean_docs_valid >= 2:
        false_positive_signals += 1  # Multiple clean docs corroborate
    if len(tamper_docs) == 1 and len(clean_docs) >= 2:
        false_positive_signals += 1  # Only one flag vs many clean

    if false_positive_signals >= 3:
        conclusion = "likely_false_positive"
        confidence = 0.8
        recommendation = "proceed_with_caution"
        message = (
            "Tamper signal appears to be a false positive. All flagged documents have "
            "correct field matches, and multiple clean documents corroborate the transaction."
        )
    elif false_positive_signals >= 2:
        conclusion = "possibly_false_positive"
        confidence = 0.6
        recommendation = "contest_with_secondary_verification"
        message = (
            "Tamper signal is moderate but unsupported by cross-document inconsistencies. "
            "Recommend contest with the document marked for secondary verification."
        )
    else:
        conclusion = "genuine_concern"
        confidence = 0.7
        recommendation = "escalate_to_human"
        message = (
            "Tamper signal is supported by field-level mismatches or insufficient "
            "corroborating evidence. Human review recommended."
        )

    return {
        "tool": "analyze_tamper_signal",
        "tamper_found": True,
        "tamper_count": len(tamper_docs),
        "clean_count": len(clean_docs),
        "tamper_with_matching_fields": tamper_with_matching_fields,
        "clean_docs_valid": clean_docs_valid,
        "false_positive_signals": false_positive_signals,
        "conclusion": conclusion,
        "confidence": round(confidence, 2),
        "recommendation": recommendation,
        "message": message,
        "tamper_details": tamper_docs,
        "clean_details": clean_docs,
    }


# ---------------------------------------------------------------------------
# Tool 3: Deadline Urgency Assessment
# ---------------------------------------------------------------------------

def get_deadline_urgency(hours_remaining: float) -> dict:
    """
    Classify the urgency level based on time remaining.

    Returns urgency band and appropriate action guidance.
    """
    if hours_remaining <= 2:
        band = "critical"
        severity = 1.0
        guidance = "Immediate decision required. No time for evidence gathering."
    elif hours_remaining <= 6:
        band = "urgent"
        severity = 0.8
        guidance = "Very limited time. Only quick-to-obtain evidence should be considered."
    elif hours_remaining <= 12:
        band = "elevated"
        severity = 0.5
        guidance = "Moderate urgency. Some time for evidence gathering if prioritized."
    elif hours_remaining <= 24:
        band = "normal"
        severity = 0.3
        guidance = "Reasonable time available. Standard evidence gathering possible."
    else:
        band = "relaxed"
        severity = 0.1
        guidance = "Ample time remaining. Full evidence gathering strategy can be pursued."

    return {
        "tool": "get_deadline_urgency",
        "hours_remaining": hours_remaining,
        "urgency_band": band,
        "severity": round(severity, 2),
        "guidance": guidance,
        "can_gather_evidence": hours_remaining > 6,
    }


# ---------------------------------------------------------------------------
# Tool 4: Cost Tradeoff Calculator
# ---------------------------------------------------------------------------

def calculate_cost_tradeoff(win_probability: float, amount: float, hours_remaining: float) -> dict:
    """
    Detailed breakeven analysis with multiple scenarios.

    Goes beyond the binary "contest or not" to show the full decision landscape:
    - Expected value of contesting
    - Expected value of accepting
    - Breakeven probability for this specific amount
    - Cost of being wrong in either direction
    """
    from decision_policy import ESCALATION_FEE, HUMAN_REVIEW_COST

    breakeven = ESCALATION_FEE / (amount + ESCALATION_FEE)

    # Expected values
    ev_contest = win_probability * 0 + (1 - win_probability) * (amount + ESCALATION_FEE)
    ev_accept = amount  # Lose the full amount
    ev_human = HUMAN_REVIEW_COST + (1 - win_probability) * amount  # Review cost + expected loss

    # Cost of being wrong
    cost_wrong_contest = amount + ESCALATION_FEE  # Contested but lost
    cost_wrong_accept = 0  # Accepted but would have won (opportunity cost = amount)

    # Decision clarity score: how far from breakeven
    distance = abs(win_probability - breakeven)
    clarity = min(1.0, distance / 0.15)  # Normalize: 15% away = fully clear

    # Optimal action based purely on expected value
    if ev_contest < ev_accept:
        optimal = "contest"
    elif ev_contest > ev_accept * 1.1:  # 10% margin
        optimal = "accept"
    else:
        optimal = "marginal"

    return {
        "tool": "calculate_cost_tradeoff",
        "win_probability": round(win_probability, 4),
        "amount": amount,
        "escalation_fee": ESCALATION_FEE,
        "breakeven_probability": round(breakeven, 4),
        "expected_loss_contest": round(ev_contest, 2),
        "expected_loss_accept": round(ev_accept, 2),
        "expected_loss_human_review": round(ev_human, 2),
        "cost_if_contest_and_lose": round(cost_wrong_contest, 2),
        "savings_if_contest_and_win": round(amount, 2),
        "decision_clarity": round(clarity, 3),
        "ev_optimal_action": optimal,
        "message": (
            f"At {win_probability:.0%} win probability for a ₹{amount:,.0f} dispute, "
            f"contesting has expected loss ₹{ev_contest:,.0f} vs accepting at ₹{ev_accept:,.0f}. "
            f"Breakeven is at {breakeven:.1%}."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 5: Similar Case Search
# ---------------------------------------------------------------------------

def search_similar_cases(
    reason_code: str,
    evidence_types_submitted: set[str],
    win_probability: float,
    limit: int = 5,
) -> dict:
    """
    Find similar past disputes by reason code and evidence pattern.

    Returns historical win rates for similar cases to contextualize the prediction.
    """
    if not os.path.exists(DATA_PATH):
        return {
            "tool": "search_similar_cases",
            "found": False,
            "message": "Dataset not available for similarity search.",
        }

    # Load and group by dispute
    with open(DATA_PATH, "r") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    disputes = {}
    for row in all_rows:
        did = row["dispute_id"]
        if did not in disputes:
            disputes[did] = []
        disputes[did].append(row)

    # Find similar disputes
    similar = []
    for did, rows in disputes.items():
        if rows[0].get("reason_code") != reason_code:
            continue

        case_types = set(r.get("evidence_type", "") for r in rows if r.get("evidence_type"))
        overlap = len(case_types & evidence_types_submitted) / max(len(case_types | evidence_types_submitted), 1)

        if overlap < 0.3:
            continue

        won = rows[0].get("dispute_outcome_won_label") in (True, "True", "true", 1, "1")
        amount = float(rows[0].get("amount", 0))

        similar.append({
            "dispute_id": did,
            "evidence_overlap": round(overlap, 2),
            "won": won,
            "amount": round(amount, 2),
            "evidence_count": len(rows),
        })

    # Sort by overlap, take top N
    similar.sort(key=lambda x: x["evidence_overlap"], reverse=True)
    similar = similar[:limit]

    if not similar:
        return {
            "tool": "search_similar_cases",
            "found": False,
            "message": f"No similar cases found for reason code '{reason_code}'.",
        }

    win_rate = sum(1 for s in similar if s["won"]) / len(similar)
    avg_amount = sum(s["amount"] for s in similar) / len(similar)

    return {
        "tool": "search_similar_cases",
        "found": True,
        "similar_count": len(similar),
        "win_rate": round(win_rate, 3),
        "avg_amount": round(avg_amount, 2),
        "current_win_probability": round(win_probability, 4),
        "cases": similar,
        "message": (
            f"Found {len(similar)} similar cases with {reason_code}. "
            f"Historical win rate: {win_rate:.0%} (vs current prediction: {win_probability:.0%})."
        ),
    }


# ---------------------------------------------------------------------------
# Tool Registry — what the agent is allowed to call
# ---------------------------------------------------------------------------

AGENT_TOOLS = {
    "check_document_consistency": {
        "function": check_document_consistency,
        "description": "Cross-validate all evidence documents against each other for field-level consistency.",
        "safe": True,
    },
    "analyze_tamper_signal": {
        "function": analyze_tamper_signal,
        "description": "Deep investigation of tamper flags — checks if they are false positives.",
        "safe": True,
    },
    "get_deadline_urgency": {
        "function": get_deadline_urgency,
        "description": "Classify time pressure urgency and recommend action speed.",
        "safe": True,
    },
    "calculate_cost_tradeoff": {
        "function": calculate_cost_tradeoff,
        "description": "Detailed expected value analysis for contest vs accept decision.",
        "safe": True,
    },
    "search_similar_cases": {
        "function": search_similar_cases,
        "description": "Find historically similar disputes and their outcomes.",
        "safe": True,
    },
}
