"""
Data schema for Dispute Defense Copilot.

Field names for Dispute and Evidence are deliberately matched to Razorpay's
real public API schema (razorpay.com/docs/api/disputes/) rather than invented,
so the prototype models an actual workflow shape. See README for citations.

Everything under `simulate_outcome` in generate_dataset.py is SYNTHETIC and
explicitly declared as such — see README "Honesty & Data Provenance" section.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ReasonCode(str, Enum):
    """Subset of Razorpay's dispute reason codes relevant to this prototype."""
    GOODS_NOT_RECEIVED = "goods_services_not_received"
    GOODS_NOT_AS_DESCRIBED = "goods_services_not_as_described"
    DUPLICATE_PROCESSING = "duplicate_processing"
    CREDIT_NOT_PROCESSED = "credit_not_processed"
    UNRECOGNIZED_TRANSACTION = "unrecognized_transaction"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"


class DisputeStatus(str, Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    WON = "won"
    LOST = "lost"
    CLOSED = "closed"


class DisputePhase(str, Enum):
    FRAUD = "fraud"
    RETRIEVAL = "retrieval"
    CHARGEBACK = "chargeback"
    ARBITRATION = "arbitration"


class EvidenceType(str, Enum):
    """
    Matches Razorpay's real evidence field names, e.g.:
    razorpay-ruby/documents/dispute.md — evidence object keys:
    shipping_proof, billing_proof, cancellation_proof, customer_communication,
    proof_of_service, explanation_letter, refund_confirmation,
    access_activity_log, refund_cancellation_policy, term_and_conditions
    """
    SHIPPING_PROOF = "shipping_proof"
    BILLING_PROOF = "billing_proof"
    CANCELLATION_PROOF = "cancellation_proof"
    CUSTOMER_COMMUNICATION = "customer_communication"
    PROOF_OF_SERVICE = "proof_of_service"
    EXPLANATION_LETTER = "explanation_letter"
    REFUND_CONFIRMATION = "refund_confirmation"
    ACCESS_ACTIVITY_LOG = "access_activity_log"
    REFUND_CANCELLATION_POLICY = "refund_cancellation_policy"
    TERM_AND_CONDITIONS = "term_and_conditions"


# Which evidence types are typically required per reason code.
# This mapping is our own product-design judgment call, informed by Razorpay's
# public "Submit Evidence" documentation (evidence varies by reason code) —
# NOT a verbatim copy of Razorpay's internal required-evidence table, since
# that isn't publicly enumerated field-by-field. Declare this in the README.
REASON_TO_REQUIRED_EVIDENCE = {
    ReasonCode.GOODS_NOT_RECEIVED: [
        EvidenceType.SHIPPING_PROOF,
        EvidenceType.CUSTOMER_COMMUNICATION,
        EvidenceType.TERM_AND_CONDITIONS,
    ],
    ReasonCode.GOODS_NOT_AS_DESCRIBED: [
        EvidenceType.SHIPPING_PROOF,
        EvidenceType.CUSTOMER_COMMUNICATION,
        EvidenceType.REFUND_CANCELLATION_POLICY,
        EvidenceType.TERM_AND_CONDITIONS,
    ],
    ReasonCode.DUPLICATE_PROCESSING: [
        EvidenceType.BILLING_PROOF,
        EvidenceType.ACCESS_ACTIVITY_LOG,
    ],
    ReasonCode.CREDIT_NOT_PROCESSED: [
        EvidenceType.REFUND_CONFIRMATION,
        EvidenceType.REFUND_CANCELLATION_POLICY,
    ],
    ReasonCode.UNRECOGNIZED_TRANSACTION: [
        EvidenceType.BILLING_PROOF,
        EvidenceType.ACCESS_ACTIVITY_LOG,
        EvidenceType.CUSTOMER_COMMUNICATION,
    ],
    ReasonCode.SUBSCRIPTION_CANCELLED: [
        EvidenceType.CANCELLATION_PROOF,
        EvidenceType.ACCESS_ACTIVITY_LOG,
        EvidenceType.TERM_AND_CONDITIONS,
    ],
}


@dataclass
class TransactionRecord:
    """Ground-truth transaction data held by the merchant/Razorpay."""
    order_id: str
    customer_name: str
    customer_address: str
    order_date: str
    delivery_date: Optional[str]
    amount: float


@dataclass
class EvidenceDocument:
    """A single piece of evidence a merchant submits."""
    evidence_type: EvidenceType
    # Fields extracted by OCR/document parsing (the "verifier" input)
    extracted_order_id: Optional[str] = None
    extracted_customer_name: Optional[str] = None
    extracted_date: Optional[str] = None
    extracted_address: Optional[str] = None
    # Ground-truth labels for training the Evidence Verifier (synthetic)
    is_valid: Optional[bool] = None          # matches transaction record correctly
    is_relevant: Optional[bool] = None       # actually addresses the reason code
    tamper_flag: Optional[bool] = None        # simulated tamper indicator


@dataclass
class Dispute:
    """Mirrors Razorpay's Dispute entity fields (id, amount, respond_by, etc.)."""
    dispute_id: str
    payment_id: str
    merchant_id: str
    amount: float
    currency: str
    reason_code: ReasonCode
    respond_by: int          # unix timestamp, matches Razorpay's real field name
    created_at: int
    status: DisputeStatus
    phase: DisputePhase
    transaction: TransactionRecord
    evidence_submitted: list = field(default_factory=list)  # list[EvidenceDocument]
    # Label for Contest Outcome Predictor training (synthetic, see generator)
    outcome_won: Optional[bool] = None
