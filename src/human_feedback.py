"""
Human Feedback Module for Dispute Defense Copilot.

Captures human overrides when an analyst disagrees with the AI recommendation.
Stores structured feedback in JSONL format for future model improvement.

This demonstrates that the system is not static — it can learn from human
corrections over time. During the hackathon, we collect the data; in
production, this would feed into a retraining pipeline.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional


_FEEDBACK_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'human_feedback.jsonl')
os.makedirs(os.path.dirname(_FEEDBACK_PATH), exist_ok=True)


# Standard override reason categories
OVERRIDE_REASONS = [
    "evidence_not_sufficient",
    "business_context_not_captured",
    "customer_exception",
    "document_issue",
    "risk_tolerance_different",
    "deadline_concern",
    "other",
]


def record_feedback(
    dispute_id: str,
    ai_recommendation: str,
    human_decision: str,
    reason: str,
    notes: Optional[str] = None,
    agent_investigated: bool = False,
) -> dict:
    """
    Record a human override of the AI recommendation.

    Parameters
    ----------
    dispute_id : str
        The dispute being overridden.
    ai_recommendation : str
        What the AI recommended (e.g., "recommend_contest").
    human_decision : str
        What the human chose instead (e.g., "accept").
    reason : str
        Category from OVERRIDE_REASONS.
    notes : str, optional
        Free-text notes from the analyst.
    agent_investigated : bool
        Whether the Case Resolution Agent investigated this case before escalation.

    Returns
    -------
    dict
        The feedback entry that was persisted.
    """
    entry = {
        "feedback_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dispute_id": dispute_id,
        "ai_recommendation": ai_recommendation,
        "human_decision": human_decision,
        "reason": reason,
        "notes": notes,
        "agent_investigated": agent_investigated,
        "is_override": ai_recommendation != human_decision,
    }

    with open(_FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return entry


def get_feedback_history(
    dispute_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Read feedback entries, optionally filtered by dispute_id."""
    if not os.path.exists(_FEEDBACK_PATH):
        return []

    entries = []
    with open(_FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if dispute_id and entry.get("dispute_id") != dispute_id:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    entries.reverse()  # Most recent first
    return entries[:limit]


def get_feedback_stats() -> dict:
    """
    Compute aggregate statistics from human feedback.

    Returns override rates, common reasons, and agreement metrics.
    """
    entries = get_feedback_history(limit=10000)

    if not entries:
        return {
            "total_feedback": 0,
            "override_rate": 0.0,
            "reason_distribution": {},
            "agreement_rate": 0.0,
            "agent_investigated_rate": 0.0,
        }

    total = len(entries)
    overrides = sum(1 for e in entries if e.get("is_override", False))
    agent_investigated = sum(1 for e in entries if e.get("agent_investigated", False))

    # Reason distribution
    reason_counts = {}
    for e in entries:
        r = e.get("reason", "unknown")
        reason_counts[r] = reason_counts.get(r, 0) + 1

    # AI recommendation distribution
    ai_rec_counts = {}
    for e in entries:
        r = e.get("ai_recommendation", "unknown")
        ai_rec_counts[r] = ai_rec_counts.get(r, 0) + 1

    # Human decision distribution
    human_dec_counts = {}
    for e in entries:
        d = e.get("human_decision", "unknown")
        human_dec_counts[d] = human_dec_counts.get(d, 0) + 1

    return {
        "total_feedback": total,
        "override_rate": round(overrides / total, 3) if total else 0.0,
        "agreement_rate": round(1 - (overrides / total), 3) if total else 0.0,
        "override_count": overrides,
        "agent_investigated_rate": round(agent_investigated / total, 3) if total else 0.0,
        "reason_distribution": reason_counts,
        "ai_recommendation_distribution": ai_rec_counts,
        "human_decision_distribution": human_dec_counts,
    }
