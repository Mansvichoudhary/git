from datetime import date as dt_date
from decimal import Decimal
from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel, Field


class CanonicalTransaction(BaseModel):
    """
    Standard Canonical Transaction Contract.
    All incoming bank statement records MUST normalize to this schema before
    entering the Part 2 Reconciliation & Anomaly Engine.
    """
    id: str = Field(description="Deterministic hash ID (e.g. TXN_7F8A1B9C2D3E4F01)")
    date: dt_date = Field(description="Normalized ISO 8601 transaction date (YYYY-MM-DD)")
    description: str = Field(description="Normalized and sanitized transaction narration")
    description_original: str = Field(description="Verbatim raw narration as present in source document")
    amount: Decimal = Field(description="Absolute monetary amount (positive decimal, 2 places)")
    type: Literal["DEBIT", "CREDIT"] = Field(description="Transaction direction: DEBIT (outflow) or CREDIT (inflow)")
    reference: Optional[str] = Field(default=None, description="Reference/UTR/Cheque/Transaction ID")
    balance: Optional[Decimal] = Field(default=None, description="Post-transaction running balance if recorded")
    currency: str = Field(default="INR", description="ISO 4217 Currency Code (e.g., INR, USD, EUR)")
    source_row: Optional[int] = Field(default=None, description="1-indexed row number from the source document")


class ParseErrorDetail(BaseModel):
    """
    Structured error or warning recorded for an unparseable or suspicious row.
    """
    row_number: Optional[int] = Field(default=None, description="Line/row index in the input file")
    field: Optional[str] = Field(default=None, description="Field name where validation failed")
    raw_value: Optional[str] = Field(default=None, description="Raw input value that triggered the issue")
    severity: Literal["WARNING", "ERROR", "FATAL"] = Field(description="Severity grade")
    message: str = Field(description="Human-readable explanation of the parsing failure")


class CanonicalStatementPackage(BaseModel):
    """
    Output bundle ready for Part 2 Reconciliation Engine consumption.
    """
    statement_id: str
    filename: str
    file_type: str
    sha256_hash: str
    total_rows: int
    valid_rows: int
    warning_count: int
    error_count: int
    currency: str = "INR"
    transactions: List[CanonicalTransaction]
    errors: List[ParseErrorDetail]
