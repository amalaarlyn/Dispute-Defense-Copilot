"""
Metrics Tracker for Dispute Defense Copilot.

Tracks the key business metrics that demonstrate value:
  1. Human Review Rate — % of cases requiring human review
  2. Escalation Precision — of escalated cases, how many genuinely needed humans
  3. Automation Coverage — % of cases fully resolved without humans
  4. Agent Resolution Rate — of cases sent to agent, how many were resolved

These metrics are computed both from the current run (in-memory) and
historically (from the audit trail).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional


_METRICS_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'agent_metrics.jsonl')
os.makedirs(os.path.dirname(_METRICS_PATH), exist_ok=True)


@dataclass
class SessionMetrics:
    """Tracks metrics for the current session / batch of disputes."""
    total_disputes: int = 0
    auto_resolved: int = 0              # Decided without agent (high/low confidence)
    agent_investigated: int = 0          # Sent to Case Resolution Agent
    agent_resolved: int = 0              # Agent resolved the ambiguity
    escalated_to_human: int = 0          # Still needed human after agent
    decisions: dict = field(default_factory=lambda: {
        "recommend_contest": 0,
        "recommend_accept": 0,
        "recommend_obtain_evidence": 0,
        "agent_resolved_contest": 0,
        "agent_resolved_accept": 0,
        "agent_resolved_obtain_evidence": 0,
        "human_review": 0,
    })

    def record_auto_decision(self, decision: str):
        """Record a case that was decided without the agent."""
        self.total_disputes += 1
        self.auto_resolved += 1
        if decision in self.decisions:
            self.decisions[decision] += 1

    def record_agent_resolution(self, final_decision: str):
        """Record a case the agent investigated and resolved."""
        self.total_disputes += 1
        self.agent_investigated += 1
        self.agent_resolved += 1
        key = f"agent_resolved_{final_decision}" if f"agent_resolved_{final_decision}" in self.decisions else final_decision
        if key in self.decisions:
            self.decisions[key] += 1

    def record_agent_escalation(self):
        """Record a case the agent couldn't resolve → escalated to human."""
        self.total_disputes += 1
        self.agent_investigated += 1
        self.escalated_to_human += 1
        self.decisions["human_review"] += 1

    @property
    def human_review_rate(self) -> float:
        """% of total disputes that need human review."""
        return self.escalated_to_human / max(self.total_disputes, 1)

    @property
    def automation_coverage(self) -> float:
        """% of disputes fully resolved without human intervention."""
        return (self.auto_resolved + self.agent_resolved) / max(self.total_disputes, 1)

    @property
    def agent_resolution_rate(self) -> float:
        """Of cases sent to agent, what % were resolved."""
        return self.agent_resolved / max(self.agent_investigated, 1)

    @property
    def baseline_human_review_rate(self) -> float:
        """What the human review rate WOULD HAVE BEEN without the agent.
        = (agent_investigated + escalated_to_human) / total = all non-auto cases."""
        return (self.agent_investigated) / max(self.total_disputes, 1)

    @property
    def human_review_reduction(self) -> float:
        """% reduction in human reviews thanks to the agent."""
        baseline = self.baseline_human_review_rate
        if baseline == 0:
            return 0.0
        return 1.0 - (self.human_review_rate / baseline)

    def to_dict(self) -> dict:
        return {
            "total_disputes": self.total_disputes,
            "auto_resolved": self.auto_resolved,
            "agent_investigated": self.agent_investigated,
            "agent_resolved": self.agent_resolved,
            "escalated_to_human": self.escalated_to_human,
            "human_review_rate": round(self.human_review_rate, 3),
            "automation_coverage": round(self.automation_coverage, 3),
            "agent_resolution_rate": round(self.agent_resolution_rate, 3),
            "baseline_human_review_rate": round(self.baseline_human_review_rate, 3),
            "human_review_reduction": round(self.human_review_reduction, 3),
            "decisions": dict(self.decisions),
        }

    def save(self):
        """Persist current metrics to JSONL."""
        with open(_METRICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), default=str) + "\n")


# ---------------------------------------------------------------------------
# Global session tracker
# ---------------------------------------------------------------------------

_session_metrics = SessionMetrics()


def get_session_metrics() -> SessionMetrics:
    """Get the current session's metrics tracker."""
    return _session_metrics


def reset_session_metrics():
    """Reset for a new session / batch."""
    global _session_metrics
    _session_metrics = SessionMetrics()


def get_historical_metrics() -> dict:
    """Load and aggregate metrics from all saved sessions."""
    if not os.path.exists(_METRICS_PATH):
        return {"sessions": 0}

    sessions = []
    with open(_METRICS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not sessions:
        return {"sessions": 0}

    total_disputes = sum(s.get("total_disputes", 0) for s in sessions)
    total_agent_investigated = sum(s.get("agent_investigated", 0) for s in sessions)
    total_agent_resolved = sum(s.get("agent_resolved", 0) for s in sessions)
    total_escalated = sum(s.get("escalated_to_human", 0) for s in sessions)
    total_auto = sum(s.get("auto_resolved", 0) for s in sessions)

    return {
        "sessions": len(sessions),
        "total_disputes": total_disputes,
        "total_auto_resolved": total_auto,
        "total_agent_investigated": total_agent_investigated,
        "total_agent_resolved": total_agent_resolved,
        "total_escalated": total_escalated,
        "overall_human_review_rate": round(total_escalated / max(total_disputes, 1), 3),
        "overall_automation_coverage": round(
            (total_auto + total_agent_resolved) / max(total_disputes, 1), 3
        ),
        "overall_agent_resolution_rate": round(
            total_agent_resolved / max(total_agent_investigated, 1), 3
        ),
    }
