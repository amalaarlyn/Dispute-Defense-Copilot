"""
Evidence Verifier — Task 1 of Dispute Defense Copilot.

Question this model answers: "Is this submitted evidence document actually
valid — i.e. does it genuinely match the transaction it's supposed to
support?"

Input: extracted fields from a document (via OCR in a real deployment; the
synthetic dataset already provides extracted_* fields) + the true transaction
record fields.
Output: VALID / INVALID classification + confidence.

This is a real, honestly-labelable binary classification task — the label
answers "does this document match this transaction," which is a ground-truth,
checkable fact, not an inference about anyone's intent.
"""

import pandas as pd
import numpy as np


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Turn raw extracted-vs-true field pairs into FUZZY similarity features.

    Deliberately does NOT use exact-match booleans: because the ground-truth
    validity label and the OCR noise are generated independently (see
    generate_dataset.py), exact-match is not a clean proxy for the label —
    genuinely valid documents can still show minor OCR mismatch, and the
    model must learn a probabilistic boundary from similarity scores instead
    of memorizing an exact-equality rule.
    """
    feats = pd.DataFrame()
    feats["order_id_sim"] = df.apply(
        lambda r: _char_similarity(str(r["extracted_order_id"]), str(r["true_order_id"])), axis=1
    )
    feats["name_sim"] = df.apply(
        lambda r: _char_similarity(str(r["extracted_customer_name"]), str(r["true_customer_name"])), axis=1
    )
    feats["date_sim"] = df.apply(
        lambda r: _char_similarity(str(r["extracted_date"]), str(r["true_date"])), axis=1
    )
    feats["address_sim"] = df.apply(
        lambda r: _char_similarity(str(r["extracted_address"]), str(r["true_address"])), axis=1
    )
    feats["tamper_flag"] = df["tamper_flag_label"].astype(str).map({"True": 1, "False": 0, "1": 1, "0": 0}).fillna(0).astype(int)
    feats["evidence_type"] = df["evidence_type"]
    feats["reason_code"] = df["reason_code"]
    return feats


def _char_similarity(a: str, b: str) -> float:
    """Normalized character-overlap ratio — a stand-in for a real fuzzy
    string matcher (e.g. Levenshtein ratio) in production."""
    if not a or not b:
        return 0.0
    a_set, b_set = set(a.lower()), set(b.lower())
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)
