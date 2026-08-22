"""
Contest Outcome Predictor for Dispute Defense Copilot.

Calibrated probabilistic model: given a dispute's evidence state (completeness,
validity ratios, per-type presence flags, amount, time remaining, phase,
reason code), predicts P(win | current evidence).

Uses GradientBoostingClassifier wrapped in CalibratedClassifierCV(isotonic)
so predicted probabilities are honest — not just decision scores.

Evaluation: ROC-AUC, Brier score, calibration curve (reliability diagram).
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from schema import EvidenceType, ReasonCode, REASON_TO_REQUIRED_EVIDENCE


# All evidence types for one-hot encoding
ALL_EVIDENCE_TYPES = sorted([et.value for et in EvidenceType])
ALL_REASON_CODES = sorted([rc.value for rc in ReasonCode])
ALL_PHASES = ["fraud", "retrieval", "chargeback", "arbitration"]


def extract_dispute_features(dispute_rows):
    """
    Given a list of evidence-document rows belonging to ONE dispute,
    compute dispute-level features for the Outcome Predictor.

    Returns a flat dict of numeric features.
    """
    if not dispute_rows:
        return None

    first = dispute_rows[0]
    reason_code_str = first.get("reason_code", "")
    amount = float(first.get("amount", 0))
    hours_remaining = float(first.get("hours_remaining_at_creation", 24))

    # Evidence types present
    present_types = set()
    valid_count = 0
    tamper_count = 0
    for row in dispute_rows:
        present_types.add(row.get("evidence_type", ""))
        if row.get("evidence_is_valid_label") in (True, "True", "true", 1, "1"):
            valid_count += 1
        if row.get("tamper_flag_label") in (True, "True", "true", 1, "1"):
            tamper_count += 1

    total_submitted = len(dispute_rows)

    # Completeness against required evidence
    try:
        reason_code = ReasonCode(reason_code_str)
        required = [et.value for et in REASON_TO_REQUIRED_EVIDENCE.get(reason_code, [])]
    except (ValueError, KeyError):
        required = []

    required_present = len(set(required) & present_types)
    completeness = required_present / max(len(required), 1)
    validity_rate = valid_count / max(total_submitted, 1)

    features = {
        "evidence_completeness": round(completeness, 4),
        "evidence_validity_rate": round(validity_rate, 4),
        "total_evidence_count": total_submitted,
        "tamper_count": tamper_count,
        "amount_log": round(np.log1p(amount), 4),
        "hours_remaining": hours_remaining,
    }

    # One-hot: evidence type presence
    for et in ALL_EVIDENCE_TYPES:
        features[f"has_{et}"] = 1.0 if et in present_types else 0.0

    # One-hot: reason code
    for rc in ALL_REASON_CODES:
        features[f"reason_{rc}"] = 1.0 if rc == reason_code_str else 0.0

    return features


def get_feature_names():
    """Return ordered list of feature names matching extract_dispute_features output."""
    names = [
        "evidence_completeness",
        "evidence_validity_rate",
        "total_evidence_count",
        "tamper_count",
        "amount_log",
        "hours_remaining",
    ]
    for et in ALL_EVIDENCE_TYPES:
        names.append(f"has_{et}")
    for rc in ALL_REASON_CODES:
        names.append(f"reason_{rc}")
    return names


def features_dict_to_array(features_dict):
    """Convert a features dict to a numpy array in canonical order."""
    names = get_feature_names()
    return np.array([features_dict.get(n, 0.0) for n in names])


def group_rows_by_dispute(rows):
    """Group CSV rows by dispute_id. Returns dict: dispute_id -> [rows]."""
    groups = {}
    for row in rows:
        did = row["dispute_id"]
        if did not in groups:
            groups[did] = []
        groups[did].append(row)
    return groups


def extract_features_batch(rows):
    """
    Extract dispute-level features and labels from all rows.
    Returns (X, y, dispute_ids) where each row in X is one dispute.
    """
    groups = group_rows_by_dispute(rows)
    feature_names = get_feature_names()

    X = []
    y = []
    dispute_ids = []

    for dispute_id, dispute_rows in groups.items():
        feats = extract_dispute_features(dispute_rows)
        if feats is None:
            continue

        x = [feats.get(n, 0.0) for n in feature_names]
        X.append(x)

        # Label: dispute outcome (same for all rows in the group)
        label = dispute_rows[0].get("dispute_outcome_won_label")
        y.append(1 if label in (True, "True", "true", 1, "1") else 0)
        dispute_ids.append(dispute_id)

    return np.array(X), np.array(y), dispute_ids


def predict_win_probability(model, features_dict):
    """
    Predict P(win) for a single dispute given its feature dict.
    Returns float probability.
    """
    x = features_dict_to_array(features_dict).reshape(1, -1)
    prob = model.predict_proba(x)[0]
    # prob[1] = P(win), prob[0] = P(lose)
    return float(prob[1])
