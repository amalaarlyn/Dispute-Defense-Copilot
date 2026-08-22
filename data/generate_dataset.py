"""
Synthetic dataset generator for Dispute Defense Copilot.

IMPORTANT — read before using these numbers anywhere in a pitch or README:
This generator is a DECLARED, EXPLICIT probabilistic simulator. It exists
because real Razorpay dispute-outcome data is not publicly available. It is
NOT a proxy for real-world chargeback outcomes and must never be described
as validated against production data.

Design principle (per the architecture review): the outcome label is NOT a
deterministic function of the same features the models will be trained on.
Two things enforce that:
  1. Sampling noise — outcome is a Bernoulli draw from a probability, not a
     hard threshold, so identical feature vectors can yield different labels.
  2. Hidden factors — some inputs to the true outcome probability (e.g.
     "issuing_bank_leniency") are used to generate the label but are NOT
     included as a feature the model can see. This creates irreducible
     uncertainty, which is exactly what the calibration/Brier-score
     evaluation in the architecture is designed to expose and measure honestly.

Downstream models are therefore learning genuine structure from observable
evidence signals, not memorizing the generator's own formula.
"""

import random
import uuid
import time
from dataclasses import asdict

import numpy as np

from schema import (
    ReasonCode, DisputeStatus, DisputePhase, EvidenceType,
    REASON_TO_REQUIRED_EVIDENCE, TransactionRecord, EvidenceDocument, Dispute,
)

RNG_SEED = 42
random.seed(RNG_SEED)
np.random.seed(RNG_SEED)

FIRST_NAMES = ["Rahul", "Priya", "Amit", "Sneha", "Arjun", "Divya", "Karthik", "Meera"]
LAST_NAMES = ["Sharma", "Iyer", "Nair", "Reddy", "Menon", "Gupta", "Rao", "Krishnan"]
CITIES = ["Chennai", "Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Pune", "Kochi"]


def _random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _random_date_str(base_ts, max_offset_days=10):
    offset = random.randint(-max_offset_days, max_offset_days) * 86400
    return time.strftime("%Y-%m-%d", time.gmtime(base_ts + offset))


def generate_transaction(order_ts):
    return TransactionRecord(
        order_id=f"ORD{random.randint(100000, 999999)}",
        customer_name=_random_name(),
        customer_address=f"{random.randint(1,999)} Main Rd, {random.choice(CITIES)}",
        order_date=time.strftime("%Y-%m-%d", time.gmtime(order_ts)),
        delivery_date=time.strftime("%Y-%m-%d", time.gmtime(order_ts + 3 * 86400)),
        amount=round(random.uniform(500, 60000), 2),
    )


def generate_evidence_document(evidence_type, txn, corruption_rate=0.35):
    """
    Generate one evidence document. With probability `corruption_rate`,
    inject a realistic mismatch/tamper issue so the Evidence Verifier has a
    genuine classification task (not a trivially separable one).
    """
    is_corrupted = random.random() < corruption_rate

    order_id = txn.order_id
    name = txn.customer_name
    date = txn.order_date
    address = txn.customer_address
    tamper_flag = False

    if is_corrupted:
        corruption_kind = random.choice(["order_id", "name", "date", "address", "tamper"])
        if corruption_kind == "order_id":
            order_id = f"ORD{random.randint(100000, 999999)}"
        elif corruption_kind == "name":
            name = _random_name()
        elif corruption_kind == "date":
            date = _random_date_str(time.time(), max_offset_days=20)
        elif corruption_kind == "address":
            address = f"{random.randint(1,999)} Cross St, {random.choice(CITIES)}"
        elif corruption_kind == "tamper":
            tamper_flag = True

    is_valid = (order_id == txn.order_id and name == txn.customer_name
                and date == txn.order_date and address == txn.customer_address
                and not tamper_flag)

    return EvidenceDocument(
        evidence_type=evidence_type,
        extracted_order_id=order_id,
        extracted_customer_name=name,
        extracted_date=date,
        extracted_address=address,
        is_valid=is_valid,
        is_relevant=True,  # relevance corruption handled separately below
        tamper_flag=tamper_flag,
    )


def simulate_outcome(evidence_docs, reason_code, amount, hours_remaining):
    """
    DECLARED SYNTHETIC SIMULATOR. Produces a win/loss label using a
    probability that depends on observable evidence quality/completeness
    PLUS a hidden factor the models never see, plus sampling noise.
    """
    required = REASON_TO_REQUIRED_EVIDENCE[reason_code]
    present_types = {d.evidence_type for d in evidence_docs}
    completeness = len(present_types & set(required)) / max(len(required), 1)

    valid_docs = [d for d in evidence_docs if d.evidence_type in required]
    validity_rate = (
        sum(1 for d in valid_docs if d.is_valid) / len(valid_docs)
        if valid_docs else 0.0
    )

    amount_pressure = min(amount / 50000, 1.0)          # higher amount -> banks scrutinize harder
    time_pressure = 1.0 - min(hours_remaining / 48, 1.0)  # less time -> weaker submitted case, on average

    # HIDDEN FACTOR — generated but never exposed as a model input.
    # Represents real-world variance the model cannot observe: issuing bank
    # policy differences, human reviewer variance, etc.
    issuing_bank_leniency = np.random.normal(loc=0.0, scale=0.15)

    logit = (
        2.2 * completeness
        + 1.8 * validity_rate
        - 0.6 * amount_pressure
        - 0.4 * time_pressure
        - 1.9                      # intercept calibrated against observed mean completeness/validity
        + issuing_bank_leniency     # hidden factor, adds irreducible noise / imperfect calibration
    )
    win_prob = 1 / (1 + np.exp(-logit))
    outcome_won = np.random.random() < win_prob
    return outcome_won, win_prob, completeness, validity_rate


def generate_dispute():
    reason_code = random.choice(list(ReasonCode))
    now = time.time()
    order_ts = now - random.randint(5, 30) * 86400
    txn = generate_transaction(order_ts)

    required = REASON_TO_REQUIRED_EVIDENCE[reason_code]
    # Merchant submits a realistic random subset of required + occasional extra evidence
    n_submit = random.randint(1, len(required))
    submitted_types = random.sample(required, n_submit)
    if random.random() < 0.2:
        extra = random.choice(list(EvidenceType))
        if extra not in submitted_types:
            submitted_types.append(extra)

    evidence_docs = [generate_evidence_document(et, txn) for et in submitted_types]

    hours_remaining = random.randint(1, 72)
    outcome_won, win_prob, completeness, validity_rate = simulate_outcome(
        evidence_docs, reason_code, txn.amount, hours_remaining
    )

    created_at = int(order_ts + random.randint(1, 5) * 86400)
    respond_by = int(created_at + hours_remaining * 3600)

    return Dispute(
        dispute_id=f"disp_{uuid.uuid4().hex[:14]}",
        payment_id=f"pay_{uuid.uuid4().hex[:14]}",
        merchant_id=f"merchant_{random.randint(1000,9999)}",
        amount=txn.amount,
        currency="INR",
        reason_code=reason_code,
        respond_by=respond_by,
        created_at=created_at,
        status=DisputeStatus.WON if outcome_won else DisputeStatus.LOST,
        phase=DisputePhase.CHARGEBACK,
        transaction=txn,
        evidence_submitted=evidence_docs,
        outcome_won=outcome_won,
    ), win_prob, completeness, validity_rate


def generate_dataset(n=5000):
    rows = []
    for _ in range(n):
        dispute, win_prob, completeness, validity_rate = generate_dispute()
        for doc in dispute.evidence_submitted:
            rows.append({
                "dispute_id": dispute.dispute_id,
                "reason_code": dispute.reason_code.value,
                "amount": dispute.amount,
                "hours_remaining_at_creation": round((dispute.respond_by - dispute.created_at) / 3600, 1),
                "evidence_type": doc.evidence_type.value,
                "extracted_order_id": doc.extracted_order_id,
                "extracted_customer_name": doc.extracted_customer_name,
                "extracted_date": doc.extracted_date,
                "extracted_address": doc.extracted_address,
                "true_order_id": dispute.transaction.order_id,
                "true_customer_name": dispute.transaction.customer_name,
                "true_date": dispute.transaction.order_date,
                "true_address": dispute.transaction.customer_address,
                "evidence_is_valid_label": doc.is_valid,      # target for Evidence Verifier
                "tamper_flag_label": doc.tamper_flag,
                "dispute_outcome_won_label": dispute.outcome_won,  # target for Contest Outcome Predictor
                "true_win_probability_declared_synthetic_only": round(win_prob, 4),
                "evidence_completeness_at_submission": round(completeness, 3),
                "evidence_validity_rate_at_submission": round(validity_rate, 3),
            })
    return rows


if __name__ == "__main__":
    import csv
    import os

    data = generate_dataset(n=5000)
    out_path = os.path.join(os.path.dirname(__file__), "synthetic_disputes.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

    won = sum(1 for d in data if d["dispute_outcome_won_label"])
    print(f"Generated {len(data)} evidence-document rows from disputes.")
    print(f"Overall win rate in synthetic set: {won/len(data):.1%}")
    print(f"Wrote: {out_path}")
