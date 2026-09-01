"""
End-to-end demo: runs one dispute through the entire pipeline.

Run from repo root:
    python -m src.demo_pipeline
"""

import os
import sys

import joblib
import pandas as pd

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "data"))
from schema import REASON_TO_REQUIRED_EVIDENCE, ReasonCode  # noqa: E402
from evidence_features import build_features  # noqa: E402
from contest_outcome_features import build_dispute_level_features  # noqa: E402
from what_if_engine import WhatIfEngine  # noqa: E402
from decision_policy import decide  # noqa: E402
from llm_explanation import build_explanation_prompt, call_llm  # noqa: E402

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_disputes.csv")


def run_for_dispute(dispute_id: str):
    raw = pd.read_csv(DATA_PATH)
    raw["dispute_outcome_won_label"] = raw["dispute_outcome_won_label"].astype(str).map(
        {"True": 1, "False": 0}
    )
    dispute_rows = raw[raw["dispute_id"] == dispute_id].copy()
    if dispute_rows.empty:
        raise ValueError(f"No such dispute_id in dataset: {dispute_id}")

    reason_code = dispute_rows["reason_code"].iloc[0]
    amount = dispute_rows["amount"].iloc[0]
    hours_remaining = dispute_rows["hours_remaining_at_creation"].iloc[0]

    # 1. Evidence Verifier
    verifier = joblib.load(os.path.join(MODELS_DIR, "evidence_verifier.joblib"))
    feat_input = build_features(dispute_rows)
    cols = ["evidence_type", "reason_code", "order_id_sim", "name_sim",
            "date_sim", "address_sim", "tamper_flag"]
    probs_valid = verifier.predict_proba(feat_input[cols])[:, 1]
    dispute_rows["predicted_valid_prob"] = probs_valid

    evidence_status = [
        {
            "type": row["evidence_type"],
            "valid": probs_valid[i] >= 0.5,
            "confidence": probs_valid[i] if probs_valid[i] >= 0.5 else 1 - probs_valid[i],
        }
        for i, (_, row) in enumerate(dispute_rows.iterrows())
    ]

    # 2. Dispute-level features + Contest Outcome Predictor
    dispute_feats_df = build_dispute_level_features(dispute_rows, verifier=verifier)
    dispute_feats = dispute_feats_df.iloc[0].to_dict()

    engine = WhatIfEngine()
    current_win_prob = engine._predict(dispute_feats)

    submitted_types = set(dispute_rows["evidence_type"])
    whatif = engine.analyze(dispute_feats, reason_code, submitted_types)

    # 3. Decision policy
    best_improvement = (
        whatif["missing_evidence_ranked"][0]["expected_improvement"]
        if whatif["missing_evidence_ranked"] else 0.0
    )
    decision = decide(
        win_prob=current_win_prob,
        amount=amount,
        hours_remaining=hours_remaining,
        any_tamper_flagged=int(dispute_feats["any_tamper_flagged"]),
        best_whatif_improvement=best_improvement,
        has_time_for_more_evidence=hours_remaining > 6,
    )

    # 4. LLM explanation (template fallback — no network in this environment)
    summary = {
        "dispute_id": dispute_id,
        "reason_code": reason_code,
        "amount": amount,
        "hours_remaining": hours_remaining,
        "evidence_status": evidence_status,
        "win_prob": current_win_prob,
        "whatif_ranked": whatif["missing_evidence_ranked"],
        "decision": decision["decision"],
        "decision_reason": decision["reason"],
    }
    prompt = build_explanation_prompt(summary)
    explanation = call_llm(prompt, use_api=False)

    # 5. Print the dashboard-style output
    print("=" * 70)
    print(f"DISPUTE {dispute_id}")
    print("=" * 70)
    print(f"Amount:            Rs.{amount:,.0f}")
    print(f"Reason:            {reason_code}")
    print(f"Hours remaining:   {hours_remaining:.0f}")
    print()
    print("Evidence:")
    for e in evidence_status:
        status = "VALID" if e["valid"] else "INVALID/UNCERTAIN"
        print(f"  {e['type']:35s} {status:20s} conf={e['confidence']:.0%}")
    print()
    print(f"Predicted win probability: {current_win_prob:.0%}")
    print()
    if whatif["missing_evidence_ranked"]:
        print("What-if analysis (missing evidence, ranked by impact):")
        for w in whatif["missing_evidence_ranked"]:
            print(f"  {w['missing_evidence_type']:30s} -> {w['projected_win_prob_if_obtained']:.0%} "
                  f"({w['expected_improvement']:+.0%})")
    else:
        print("No missing required evidence.")
    print()
    print(f"RECOMMENDATION: {decision['decision']}")
    print(f"Reason: {decision['reason']}")
    print()
    print("Explanation:")
    print(explanation)
    print()
    print(f"[Audit trail entry would be written here: {dispute_id}, all values above, timestamped]")


if __name__ == "__main__":
    raw = pd.read_csv(DATA_PATH)
    sample_id = raw["dispute_id"].iloc[0]
    print(f"(Running demo on dispute_id={sample_id} — pass a specific dispute_id to run_for_dispute() for others)\n")
    run_for_dispute(sample_id)
