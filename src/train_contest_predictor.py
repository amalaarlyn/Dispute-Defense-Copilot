"""
Contest Outcome Predictor — Task 2 of Dispute Defense Copilot.

Question: "Given the current evidence state, what's the probability this
contest wins?" Evaluated as a probability estimation task (AUC, Brier score,
calibration), not primarily as a classifier — see README evaluation table.

Run from repo root:
    python -m src.train_contest_predictor
"""

import os
import sys

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, brier_score_loss, precision_score, recall_score
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import joblib

sys.path.append(os.path.dirname(__file__))
from contest_outcome_features import build_dispute_level_features  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_disputes.csv")
RANDOM_STATE = 42


def load_dispute_features():
    df = pd.read_csv(DATA_PATH)
    df["dispute_outcome_won_label"] = df["dispute_outcome_won_label"].astype(str).map(
        {"True": 1, "False": 0}
    )
    feats = build_dispute_level_features(df)
    return feats


def main():
    feats = load_dispute_features()
    y = feats["dispute_outcome_won_label"]

    numeric_cols = [
        "amount", "hours_remaining_at_creation", "predicted_completeness",
        "predicted_validity_rate", "min_predicted_validity", "any_tamper_flagged",
        "n_documents_submitted",
    ]
    categorical_cols = ["reason_code"]

    X_train, X_test, y_train, y_test = train_test_split(
        feats, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )

    preprocessor = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
    ], remainder="passthrough")

    base_model = RandomForestClassifier(
        n_estimators=200, max_depth=5, random_state=RANDOM_STATE
    )

    pipeline = Pipeline([
        ("preprocess", preprocessor),
        ("clf", CalibratedClassifierCV(base_model, method="isotonic", cv=5)),
    ])

    cols = categorical_cols + numeric_cols
    pipeline.fit(X_train[cols], y_train)
    probs = pipeline.predict_proba(X_test[cols])[:, 1]
    preds = (probs >= 0.5).astype(int)

    auc = roc_auc_score(y_test, probs)
    brier = brier_score_loss(y_test, probs)
    precision = precision_score(y_test, preds)
    recall = recall_score(y_test, preds)

    print("=" * 60)
    print("CONTEST OUTCOME PREDICTOR — held-out test set results")
    print("=" * 60)
    print(f"Test set size: {len(y_test)} disputes")
    print(f"Base win rate in test set: {y_test.mean():.1%}")
    print()
    print(f"ROC-AUC:     {auc:.3f}")
    print(f"Brier score: {brier:.3f}  (lower is better; 0 = perfect, 0.25 = uninformative)")
    print(f"Precision @ 0.5 threshold: {precision:.3f}")
    print(f"Recall @ 0.5 threshold:    {recall:.3f}")
    print()

    if auc > 0.98:
        print("WARNING: AUC is suspiciously high — check for label leakage "
              "before trusting this number (see Evidence Verifier incident).")

    # Calibration curve — "when we say 80%, do cases actually win ~80% of the time?"
    frac_pos, mean_pred = calibration_curve(y_test, probs, n_bins=10, strategy="quantile")
    plt.figure(figsize=(5, 5))
    plt.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")
    plt.plot(mean_pred, frac_pos, marker="o", label="Contest Outcome Predictor")
    plt.xlabel("Mean predicted win probability")
    plt.ylabel("Observed win fraction")
    plt.title("Calibration curve — Contest Outcome Predictor")
    plt.legend()
    plt.tight_layout()
    fig_path = os.path.join(os.path.dirname(__file__), "..", "models", "calibration_curve.png")
    plt.savefig(fig_path, dpi=120)
    print(f"Saved calibration curve to {fig_path}")

    model_path = os.path.join(os.path.dirname(__file__), "..", "models", "contest_predictor.joblib")
    joblib.dump(pipeline, model_path)
    print(f"Saved model to {model_path}")

    return pipeline


if __name__ == "__main__":
    main()
