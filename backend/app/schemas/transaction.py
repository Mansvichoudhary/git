from datetime import date as dt_date
from decimal import Decimal
from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel, Field


class TransactionProvenance(BaseModel):
    """
    Audit provenance trace linking canonical record directly to file, page, and row.
    """
    file_id: str
    filename: str
    page: int = 1
    row: int


class CanonicalTransaction(BaseModel):
    """
    Standard Canonical Transaction Contract (Section 27).
    All incoming financial files (bank statements, ledgers, invoice registers)
    normalize to this schema before entering Part 2 Reconciliation & Anomaly Engine.
    """
    id: str = Field(description="Deterministic hash ID (e.g. TXN_7F8A1B9C2D3E4F01)")
    reconciliation_id: Optional[str] = Field(default="REC_DEMO_01", description="Parent reconciliation ID")
    source_id: Optional[str] = Field(default="SRC_DEMO_BANK", description="Parent financial source ID")
    source_type: str = Field(default="BANK_STATEMENT", description="BANK_STATEMENT, ACCOUNTING_LEDGER, etc.")

    date: dt_date = Field(description="Normalized ISO 8601 transaction date (YYYY-MM-DD)")
    description: str = Field(description="Normalized and sanitized transaction narration")
    description_original: str = Field(description="Verbatim raw narration as present in source document")

    amount: Decimal = Field(description="Absolute monetary amount (positive decimal, 2 places)")
    type: Literal["DEBIT", "CREDIT"] = Field(description="Transaction direction: DEBIT (outflow) or CREDIT (inflow)")

    reference: Optional[str] = Field(default=None, description="Reference/UTR/Cheque/Transaction ID")
    currency: str = Field(default="INR", description="ISO 4217 Currency Code (default: INR)")
    balance: Optional[Decimal] = Field(default=None, description="Running balance if recorded")

    account_id: Optional[str] = Field(default=None, description="Account identifier")
    transaction_id: Optional[str] = Field(default=None, description="Original transaction ID if present")
    external_id: Optional[str] = Field(default=None, description="External ERP/Core banking ID")

    invoice_id: Optional[str] = Field(default=None, description="Associated invoice number")
    vendor: Optional[str] = Field(default=None, description="Identified vendor/counterparty")
    customer: Optional[str] = Field(default=None, description="Identified customer")

    provenance: Dict[str, Any] = Field(default_factory=dict, description="File/page/row origin provenance")
    source_row: Optional[int] = Field(default=None, description="1-indexed row number from the source document")


class ControlTotalsSummary(BaseModel):
    """
    Financial Control Totals (Section 19).
    Opening + Credits - Debits = Expected Closing Balance.
    """
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    total_debits: Decimal = Decimal("0.00")
    total_credits: Decimal = Decimal("0.00")
    transaction_count: int = 0
    expected_closing_balance: Optional[Decimal] = None
    control_difference: Decimal = Decimal("0.00")
    status: Literal["VERIFIED", "CONTROL_TOTAL_MISMATCH", "NOT_APPLICABLE"] = "NOT_APPLICABLE"


class ParseErrorDetail(BaseModel):
    """
    Structured error or warning recorded for an unparseable or suspicious row (Section 21).
    """
    row_number: Optional[int] = Field(default=None, description="Line/row index in the input file")
    page_number: int = Field(default=1, description="Page number for PDF documents")
    field: Optional[str] = Field(default=None, description="Field name where validation failed")
    raw_value: Optional[str] = Field(default=None, description="Raw input value that triggered the issue")
    severity: Literal["WARNING", "ERROR", "FATAL"] = Field(description="Severity grade")
    message: str = Field(description="Human-readable explanation of the parsing failure")


class CanonicalStatementPackage(BaseModel):
    """
    Output bundle ready for Part 2 Reconciliation Engine consumption (Section 12 & 27).
    """
    statement_id: str
    reconciliation_id: str = "REC_DEMO_01"
    source_id: str = "SRC_DEMO_BANK"
    source_type: str = "BANK_STATEMENT"
    account: str = "DEFAULT_ACC"
    currency: str = "INR"
    filename: str
    file_type: str
    sha256_hash: str
    total_rows: int
    valid_rows: int
    warning_count: int
    error_count: int
    control_totals: ControlTotalsSummary = Field(default_factory=ControlTotalsSummary)
    transactions: List[CanonicalTransaction]
    errors: List[ParseErrorDetail]
    metadata: Dict[str, Any] = Field(default_factory=dict)
