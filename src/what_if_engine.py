"""
Evidence What-If Engine — Task 3 of Dispute Defense Copilot.

Given a dispute's current evidence state, estimates win probability if each
currently-missing required evidence type were additionally obtained, and
ranks missing evidence by expected improvement. This is the "get delivery
proof first, here's why" output.

Assumption, stated explicitly (do not hide this in the demo): when
simulating "evidence X obtained," we assume it would be valid with
probability equal to the OBSERVED validity rate of that evidence type in the
training data (not assumed to be perfectly valid) — obtaining a document
doesn't guarantee it's a strong one. This keeps the what-if projection
honest rather than overstating the benefit of "just get more evidence."
"""

import os
import sys

import joblib
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "data"))
from schema import REASON_TO_REQUIRED_EVIDENCE, ReasonCode  # noqa: E402

CONTEST_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "contest_predictor.joblib")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_disputes.csv")


def _observed_validity_rate_by_type(evidence_df: pd.DataFrame) -> dict:
    """Historical validity rate per evidence type, used to estimate the
    realistic value of 'obtaining' a given missing document — not assumed
    to be 100% valid just because it was newly obtained."""
    df = evidence_df.copy()
    df["is_valid_bool"] = df["evidence_is_valid_label"].astype(str).eq("True")
    return df.groupby("evidence_type")["is_valid_bool"].mean().to_dict()


class WhatIfEngine:
    def __init__(self):
        self.model = joblib.load(CONTEST_MODEL_PATH)
        raw = pd.read_csv(DATA_PATH)
        self.validity_rate_by_type = _observed_validity_rate_by_type(raw)
        self.numeric_cols = [
            "amount", "hours_remaining_at_creation", "predicted_completeness",
            "predicted_validity_rate", "min_predicted_validity", "any_tamper_flagged",
            "n_documents_submitted",
        ]
        self.categorical_cols = ["reason_code"]

    def _predict(self, dispute_features: dict) -> float:
        row = pd.DataFrame([dispute_features])
        cols = self.categorical_cols + self.numeric_cols
        return float(self.model.predict_proba(row[cols])[:, 1][0])

    def analyze(self, current_features: dict, reason_code: str, submitted_evidence_types: set) -> dict:
        """
        current_features: the dispute-level feature dict as produced by
        contest_outcome_features.build_dispute_level_features (one row,
        as a dict) for the CURRENT evidence state.
        """
        required_types = set(e.value for e in REASON_TO_REQUIRED_EVIDENCE[ReasonCode(reason_code)])
        missing_types = required_types - submitted_evidence_types

        current_win_prob = self._predict(current_features)

        results = []
        for missing_type in missing_types:
            hypothetical = dict(current_features)
            n_required = len(required_types)
            new_completeness = (len(required_types & submitted_evidence_types) + 1) / max(n_required, 1)
            expected_validity_of_new_doc = self.validity_rate_by_type.get(missing_type, 0.65)

            # Recompute validity_rate as a weighted average including the
            # hypothetical new (probabilistically valid) document.
            n_current = hypothetical["n_documents_submitted"]
            new_validity_rate = (
                hypothetical["predicted_validity_rate"] * n_current + expected_validity_of_new_doc
            ) / (n_current + 1)

            hypothetical["predicted_completeness"] = new_completeness
            hypothetical["predicted_validity_rate"] = new_validity_rate
            hypothetical["n_documents_submitted"] = n_current + 1

            hypothetical_win_prob = self._predict(hypothetical)

            results.append({
                "missing_evidence_type": missing_type,
                "current_win_prob": round(current_win_prob, 3),
                "projected_win_prob_if_obtained": round(hypothetical_win_prob, 3),
                "expected_improvement": round(hypothetical_win_prob - current_win_prob, 3),
                "assumed_validity_rate_of_new_doc": round(expected_validity_of_new_doc, 3),
            })

        results.sort(key=lambda r: r["expected_improvement"], reverse=True)
        return {
            "current_win_prob": round(current_win_prob, 3),
            "missing_evidence_ranked": results,
        }
