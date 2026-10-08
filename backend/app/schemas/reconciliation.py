from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import date as dt_date, datetime
from decimal import Decimal
from app.schemas.transaction import CanonicalTransaction


class MatchScoreDetail(BaseModel):
    amount_score: float = 0.0
    date_score: float = 0.0
    description_score: float = 0.0
    reference_score: float = 0.0
    type_score: float = 0.0
    total_confidence: float = 0.0


class MatchResultItem(BaseModel):
    id: str
    reconciliation_run_id: str
    bank_transaction_id: Optional[str] = None
    company_transaction_id: Optional[str] = None
    bank_transaction: Optional[CanonicalTransaction] = None
    company_transaction: Optional[CanonicalTransaction] = None
    status: Literal["MATCHED", "PROBABLE_MATCH", "UNMATCHED"]
    match_type: Literal["EXACT", "REFERENCE", "FUZZY", "DATE_TOLERANCE", "COMPOSITE", "NONE"]
    confidence: float
    amount_difference: Decimal = Decimal("0.00")
    date_difference_days: int = 0
    scores: MatchScoreDetail = Field(default_factory=MatchScoreDetail)
    reasons: List[str] = Field(default_factory=list)
    created_at: str


class AnomalyItem(BaseModel):
    id: str
    reconciliation_run_id: str
    transaction_id: str
    candidate_transaction_id: Optional[str] = None
    transaction: Optional[CanonicalTransaction] = None
    candidate_transaction: Optional[CanonicalTransaction] = None
    type: Literal[
        "DUPLICATE_TRANSACTION",
        "DATE_MISMATCH",
        "AMOUNT_MISMATCH",
        "MISSING_IN_COMPANY",
        "MISSING_IN_BANK",
        "DESCRIPTION_MISMATCH",
        "REFERENCE_MISMATCH",
        "DEBIT_CREDIT_MISMATCH",
        "COMPOSITE_MATCH",
        "CONTROL_TOTAL_MISMATCH"
    ]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    status: Literal["PENDING", "INVESTIGATING", "CONFIRMED", "REJECTED", "RESOLVED"] = "PENDING"
    amount_difference: Decimal = Decimal("0.00")
    date_difference_days: int = 0
    evidence: List[str] = Field(default_factory=list)
    created_at: str


class AIInvestigationResult(BaseModel):
    id: str
    anomaly_id: str
    finding: str
    anomaly_type: str
    conclusion: str
    confidence: float
    risk: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    evidence: List[str] = Field(default_factory=list)
    recommended_action: str
    ai_model: str = "gemini-1.5-flash"
    created_at: str


class HumanReviewSubmission(BaseModel):
    action: Literal["CONFIRM_MATCH", "MARK_UNMATCHED", "MARK_DUPLICATE"]
    comment: Optional[str] = None
    user_id: str = "auditor_user"


class ReconciliationRunResponse(BaseModel):
    id: str
    reconciliation_id: str
    bank_source_id: Optional[str] = None
    company_source_id: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str


class ReconciliationSummaryReport(BaseModel):
    run_id: str
    reconciliation_id: str
    status: Literal["RECONCILIATION COMPLETE", "REVIEW REQUIRED"]
    total_bank_transactions: int
    total_company_transactions: int
    matched_count: int
    probable_match_count: int
    unmatched_count: int
    anomalies_count: int
    duplicate_count: int
    total_amount_difference: Decimal
    matches: List[MatchResultItem] = Field(default_factory=list)
    anomalies: List[AnomalyItem] = Field(default_factory=list)
    generated_at: str
