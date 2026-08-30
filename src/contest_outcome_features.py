"""
Builds per-dispute features for the Contest Outcome Predictor.

Deliberately uses the trained Evidence Verifier's PREDICTED validity
(predict_proba), not the synthetic ground-truth `evidence_is_valid_label`,
and does NOT use the generator's own `evidence_completeness_at_submission` /
`evidence_validity_rate_at_submission` columns directly — those exist only
for debugging the simulator (see generate_dataset.py) and would be
privileged information unavailable at real inference time. Recomputing
completeness from observable submitted-evidence-types keeps this feature
set something a real system could actually produce.
"""

import os
import sys

import joblib
import pandas as pd
import numpy as np

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "data"))
from schema import REASON_TO_REQUIRED_EVIDENCE, ReasonCode  # noqa: E402
from evidence_features import build_features  # noqa: E402

VERIFIER_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "evidence_verifier.joblib")


def _required_count(reason_code_str):
    rc = ReasonCode(reason_code_str)
    return len(REASON_TO_REQUIRED_EVIDENCE[rc])


def build_dispute_level_features(evidence_df: pd.DataFrame, verifier=None) -> pd.DataFrame:
    """
    evidence_df: the raw evidence-document-level rows (one row per submitted
    document, as produced by generate_dataset.py).

    Returns one row per dispute_id with aggregated, model-predicted features.
    """
    if verifier is None:
        verifier = joblib.load(VERIFIER_PATH)

    feat_input = build_features(evidence_df)
    categorical_cols = ["evidence_type", "reason_code"]
    numeric_cols = ["order_id_sim", "name_sim", "date_sim", "address_sim", "tamper_flag"]
    predicted_valid_prob = verifier.predict_proba(feat_input[categorical_cols + numeric_cols])[:, 1]

    evidence_df = evidence_df.copy()
    evidence_df["predicted_valid_prob"] = predicted_valid_prob

    rows = []
    for dispute_id, group in evidence_df.groupby("dispute_id"):
        reason_code = group["reason_code"].iloc[0]
        n_required = _required_count(reason_code)
        n_submitted_required_types = len(
            set(group["evidence_type"]) & set(
                e.value for e in REASON_TO_REQUIRED_EVIDENCE[ReasonCode(reason_code)]
            )
        )
        predicted_completeness = n_submitted_required_types / max(n_required, 1)
        predicted_validity_rate = group["predicted_valid_prob"].mean()
        min_predicted_validity = group["predicted_valid_prob"].min()
        any_tamper_flagged = int(group["tamper_flag_label"].astype(str).eq("True").any())

        rows.append({
            "dispute_id": dispute_id,
            "reason_code": reason_code,
            "amount": group["amount"].iloc[0],
            "hours_remaining_at_creation": group["hours_remaining_at_creation"].iloc[0],
            "predicted_completeness": predicted_completeness,
            "predicted_validity_rate": predicted_validity_rate,
            "min_predicted_validity": min_predicted_validity,
            "any_tamper_flagged": any_tamper_flagged,
            "n_documents_submitted": len(group),
            "dispute_outcome_won_label": group["dispute_outcome_won_label"].iloc[0],
        })

    return pd.DataFrame(rows)
