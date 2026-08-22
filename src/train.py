"""
Training script for Dispute Defense Copilot.

End-to-end training and evaluation of the Evidence Verifier and Outcome Predictor.
Uses synthetic data. Saves models and evaluation metrics.
"""

import sys
import os
import csv
import json
import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, brier_score_loss, confusion_matrix

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data'))
from evidence_verifier import extract_features_batch as extract_verifier_features
from outcome_predictor import extract_features_batch as extract_predictor_features
from decision_policy import evaluate_decision_policy, cost_weighted_evaluation

def load_data(filepath):
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)

def train_verifier(train_rows, test_rows):
    print("Training Evidence Verifier...")
    X_train, y_train_valid, _ = extract_verifier_features(train_rows)
    X_test, y_test_valid, _ = extract_verifier_features(test_rows)
    
    # Base model
    base_clf = GradientBoostingClassifier(n_estimators=100, random_state=42)
    # Calibrated
    clf = CalibratedClassifierCV(base_clf, method='isotonic', cv=3)
    clf.fit(X_train, y_train_valid)
    
    # Evaluate
    y_pred = clf.predict(X_test)
    cm = confusion_matrix(y_test_valid, y_pred)
    acc = np.mean(y_pred == y_test_valid)
    
    print(f"Verifier Accuracy: {acc:.3f}")
    print(f"Verifier Confusion Matrix:\n{cm}")
    
    return clf

def train_predictor(train_rows, test_rows):
    print("\nTraining Contest Outcome Predictor...")
    X_train, y_train, _ = extract_predictor_features(train_rows)
    X_test, y_test, test_dispute_ids = extract_predictor_features(test_rows)
    
    base_clf = GradientBoostingClassifier(n_estimators=150, max_depth=4, random_state=42)
    clf = CalibratedClassifierCV(base_clf, method='isotonic', cv=5)
    clf.fit(X_train, y_train)
    
    # Evaluate
    y_prob = clf.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)
    
    auc = roc_auc_score(y_test, y_prob)
    brier = brier_score_loss(y_test, y_prob)
    cm = confusion_matrix(y_test, y_pred)
    acc = np.mean(y_pred == y_test)
    
    print(f"Predictor ROC-AUC: {auc:.3f}")
    print(f"Predictor Brier Score: {brier:.4f}")
    print(f"Predictor Accuracy: {acc:.3f}")
    print(f"Predictor Confusion Matrix:\n{cm}")
    
    return clf, X_test, y_test, y_prob, test_dispute_ids

def run_policy_evaluation(test_rows, predictor, X_test, y_test, y_prob, test_dispute_ids):
    print("\nRunning Decision Policy Evaluation on Test Set...")
    # Group test rows by dispute_id
    groups = {}
    for row in test_rows:
        did = row["dispute_id"]
        if did not in groups:
            groups[did] = []
        groups[did].append(row)
        
    policy_actions = []
    amounts = []
    
    for i, dispute_id in enumerate(test_dispute_ids):
        dispute_rows = groups[dispute_id]
        amount = float(dispute_rows[0].get("amount", 0))
        hours_remaining = float(dispute_rows[0].get("hours_remaining_at_creation", 24))
        
        # We need verifier results and completeness to run the policy
        # For evaluation, we'll just use the ground truth from the synthetic data
        # to approximate what the verifier and completeness extractor would output.
        # This keeps the evaluation self-contained for the predictor + policy.
        
        completeness = X_test[i][0] # first feature is completeness
        
        # Mock verifier results based on synthetic labels for the policy
        verifier_results = []
        for r in dispute_rows:
            verifier_results.append({
                "features": {"tamper_flag": r.get("tamper_flag_label") in (True, "True", "true", 1, "1")},
                "field_mismatches": [] # Simplified for evaluation
            })
            
        decision = evaluate_decision_policy(
            win_prob=y_prob[i],
            evidence_completeness=completeness,
            verifier_results=verifier_results,
            whatif_results=[], # Not evaluating what-if impact on historical cost here
            hours_remaining=hours_remaining
        )
        policy_actions.append(decision["action"])
        amounts.append(amount)
        
    cost_metrics = cost_weighted_evaluation(y_prob, y_test, amounts, policy_actions)
    print("Cost-Weighted Evaluation:")
    for k, v in cost_metrics.items():
        print(f"  {k}: ₹{v:,.2f}")
        
    return cost_metrics

def main():
    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_disputes.csv")
    if not os.path.exists(data_path):
        print("Data not found. Please run data/generate_dataset.py first.")
        sys.exit(1)
        
    rows = load_data(data_path)
    
    # We must split by dispute_id, not by row, to prevent leakage
    dispute_ids = list(set([r["dispute_id"] for r in rows]))
    train_ids, test_ids = train_test_split(dispute_ids, test_size=0.2, random_state=42)
    
    train_ids_set = set(train_ids)
    train_rows = [r for r in rows if r["dispute_id"] in train_ids_set]
    test_rows = [r for r in rows if r["dispute_id"] not in train_ids_set]
    
    print(f"Train disputes: {len(train_ids)}, Test disputes: {len(test_ids)}")
    
    verifier = train_verifier(train_rows, test_rows)
    predictor, X_test, y_test, y_prob, test_dispute_ids = train_predictor(train_rows, test_rows)
    
    cost_metrics = run_policy_evaluation(test_rows, predictor, X_test, y_test, y_prob, test_dispute_ids)
    
    # Save models
    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    os.makedirs(models_dir, exist_ok=True)
    
    joblib.dump(verifier, os.path.join(models_dir, "evidence_verifier.joblib"))
    joblib.dump(predictor, os.path.join(models_dir, "outcome_predictor.joblib"))
    
    # Save metrics
    metrics = {
        "cost_metrics": cost_metrics
    }
    with open(os.path.join(models_dir, "evaluation_report.json"), "w") as f:
        json.dump(metrics, f, indent=2)
        
    print("\nModels and metrics saved to models/")

if __name__ == "__main__":
    main()
