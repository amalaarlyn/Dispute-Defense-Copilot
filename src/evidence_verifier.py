"""
Evidence Verifier for Dispute Defense Copilot.

Per-document binary classifier: given an evidence document and the merchant's
ground-truth transaction record, determines whether the document is VALID
(fields match, no tampering) and RELEVANT (addresses the dispute reason code).

Features are rule-based cross-checks (fuzzy string matching, exact field
comparison) — not raw text. The classifier learns which combinations of
match signals best predict the synthetic is_valid label.
"""

import sys
import os
import numpy as np
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from schema import EvidenceType, REASON_TO_REQUIRED_EVIDENCE, ReasonCode


def _fuzzy_ratio(a, b):
    """SequenceMatcher-based fuzzy string similarity in [0, 1]."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def extract_document_features(doc_row):
    """
    Extract features for a single evidence document row (dict from CSV).
    Returns a dict of numeric features suitable for model training.
    """
    order_id_match = float(doc_row.get("extracted_order_id", "") == doc_row.get("true_order_id", ""))
    name_similarity = _fuzzy_ratio(
        doc_row.get("extracted_customer_name", ""),
        doc_row.get("true_customer_name", "")
    )
    date_match = float(doc_row.get("extracted_date", "") == doc_row.get("true_date", ""))
    address_similarity = _fuzzy_ratio(
        doc_row.get("extracted_address", ""),
        doc_row.get("true_address", "")
    )

    # Check if this evidence type is in the required list for the reason code
    reason_code_str = doc_row.get("reason_code", "")
    evidence_type_str = doc_row.get("evidence_type", "")
    try:
        reason_code = ReasonCode(reason_code_str)
        evidence_type = EvidenceType(evidence_type_str)
        required = REASON_TO_REQUIRED_EVIDENCE.get(reason_code, [])
        is_relevant = float(evidence_type in required)
    except (ValueError, KeyError):
        is_relevant = 0.0

    return {
        "order_id_match": order_id_match,
        "name_similarity": round(name_similarity, 4),
        "date_match": date_match,
        "address_similarity": round(address_similarity, 4),
        "is_relevant": is_relevant,
        # Composite: how many fields match out of 4
        "field_match_count": order_id_match + float(name_similarity > 0.85) + date_match + float(address_similarity > 0.85),
    }


def extract_features_batch(rows):
    """Extract features for a batch of document rows. Returns (X, y_valid, y_tamper)."""
    X = []
    y_valid = []
    y_tamper = []
    for row in rows:
        feats = extract_document_features(row)
        X.append([
            feats["order_id_match"],
            feats["name_similarity"],
            feats["date_match"],
            feats["address_similarity"],
            feats["is_relevant"],
            feats["field_match_count"],
        ])
        y_valid.append(1 if row.get("evidence_is_valid_label") in (True, "True", "true", 1, "1") else 0)
        y_tamper.append(1 if row.get("tamper_flag_label") in (True, "True", "true", 1, "1") else 0)
    return np.array(X), np.array(y_valid), np.array(y_tamper)


FEATURE_NAMES = [
    "order_id_match",
    "name_similarity",
    "date_match",
    "address_similarity",
    "is_relevant",
    "field_match_count",
]


def verify_single_document(model, doc_row):
    """
    Run the trained verifier on a single document row.
    Returns dict with validity prediction, confidence, and field-level breakdown.

    The retrained verifier expects a 7-column DataFrame:
    [evidence_type, reason_code, order_id_sim, name_sim, date_sim, address_sim, tamper_flag]
    produced by data.evidence_features.build_features.
    """
    import pandas as pd

    feats = extract_document_features(doc_row)

    # Build a single-row DataFrame matching the training schema
    row_df = pd.DataFrame([{
        "evidence_type": doc_row.get("evidence_type", ""),
        "reason_code": doc_row.get("reason_code", ""),
        "order_id_sim": feats["order_id_match"],
        "name_sim": feats["name_similarity"],
        "date_sim": feats["date_match"],
        "address_sim": feats["address_similarity"],
        "tamper_flag": int(doc_row.get("tamper_flag_label") in (True, "True", "true", 1, "1")),
    }])

    cols = ["evidence_type", "reason_code", "order_id_sim", "name_sim", "date_sim", "address_sim", "tamper_flag"]
    prob = model.predict_proba(row_df[cols])[0]
    predicted_valid = bool(prob[1] >= 0.5)
    confidence = float(max(prob))

    # Build human-readable field mismatch report
    mismatches = []
    if feats["order_id_match"] < 1.0:
        mismatches.append({
            "field": "order_id",
            "extracted": doc_row.get("extracted_order_id", ""),
            "expected": doc_row.get("true_order_id", ""),
            "match_score": feats["order_id_match"],
        })
    if feats["name_similarity"] < 0.85:
        mismatches.append({
            "field": "customer_name",
            "extracted": doc_row.get("extracted_customer_name", ""),
            "expected": doc_row.get("true_customer_name", ""),
            "match_score": feats["name_similarity"],
        })
    if feats["date_match"] < 1.0:
        mismatches.append({
            "field": "date",
            "extracted": doc_row.get("extracted_date", ""),
            "expected": doc_row.get("true_date", ""),
            "match_score": feats["date_match"],
        })
    if feats["address_similarity"] < 0.85:
        mismatches.append({
            "field": "address",
            "extracted": doc_row.get("extracted_address", ""),
            "expected": doc_row.get("true_address", ""),
            "match_score": feats["address_similarity"],
        })

    return {
        "evidence_type": doc_row.get("evidence_type", ""),
        "predicted_valid": predicted_valid,
        "confidence": round(confidence, 4),
        "is_relevant": bool(feats["is_relevant"]),
        "field_mismatches": mismatches,
        "field_match_count": int(feats["field_match_count"]),
        "features": feats,
    }

