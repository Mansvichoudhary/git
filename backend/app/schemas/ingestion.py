from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from .transaction import CanonicalTransaction, ParseErrorDetail, ControlTotalsSummary


class CompanyCreate(BaseModel):
    company_name: str
    legal_name: Optional[str] = None
    industry: Optional[str] = "Fintech"
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    country: str = "India"
    timezone: str = "Asia/Kolkata"
    base_currency: str = "INR"


class CompanyResponse(BaseModel):
    id: str
    company_name: str
    legal_name: Optional[str] = None
    industry: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    country: str
    timezone: str
    base_currency: str
    logo_url: Optional[str] = None
    created_at: str


class ReconciliationCreate(BaseModel):
    company_id: str
    name: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class ReconciliationResponse(BaseModel):
    id: str
    company_id: str
    name: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    status: str
    created_at: str


class SourceCreate(BaseModel):
    reconciliation_id: str
    source_type: Literal[
        "BANK_STATEMENT",
        "ACCOUNTING_LEDGER",
        "PAYMENT_REGISTER",
        "INVOICE_REGISTER",
        "SALES_REGISTER",
        "PURCHASE_REGISTER",
        "ERP_EXPORT",
        "OTHER"
    ]
    name: str


class SourceResponse(BaseModel):
    id: str
    reconciliation_id: str
    source_type: str
    name: str
    status: str
    created_at: str


class FileUploadResponse(BaseModel):
    file_id: str
    job_id: str
    reconciliation_id: Optional[str] = None
    source_id: Optional[str] = None
    source_type: Optional[str] = "BANK_STATEMENT"
    filename: str
    file_size: int
    mime_type: str
    sha256_hash: str
    status: str
    is_duplicate: bool = False
    message: str


class ColumnMappingItem(BaseModel):
    source_column: str
    target_field: Optional[str] = None
    confidence: float
    method: Literal["exact", "alias", "fuzzy", "heuristic", "ai", "learned", "manual"]
    sample_values: List[str] = Field(default_factory=list)


class DetectFormatResponse(BaseModel):
    job_id: str
    file_type: str
    detected_delimiter: Optional[str] = None
    header_row_index: int
    detected_headers: List[str]
    suggested_mappings: List[ColumnMappingItem]
    confidence_score: float
    status: Literal["READY_FOR_EXECUTION", "NEEDS_REVIEW"]
    sample_rows: List[Dict[str, Any]]


class ColumnMappingSubmission(BaseModel):
    mappings: Dict[str, str]
    currency: str = "INR"
    account_number: Optional[str] = "DEFAULT_ACC"
    source_type: str = "BANK_STATEMENT"
    remember_rules: bool = True  # Persistent mapping learning (Section 16)


class ParseExecutionResponse(BaseModel):
    job_id: str
    status: str
    total_rows: int
    valid_rows: int
    warning_rows: int
    error_rows: int
    control_totals: ControlTotalsSummary = Field(default_factory=ControlTotalsSummary)
    transactions_preview: List[CanonicalTransaction] = Field(default_factory=list)
    errors: List[ParseErrorDetail] = Field(default_factory=list)
