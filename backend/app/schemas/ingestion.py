from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from .transaction import CanonicalTransaction, ParseErrorDetail


class FileUploadResponse(BaseModel):
    file_id: str
    job_id: str
    filename: str
    file_size: int
    mime_type: str
    sha256_hash: str
    status: str
    message: str


class ColumnMappingItem(BaseModel):
    source_column: str
    target_field: Optional[str] = None  # date, description, amount, type, debit, credit, reference, balance, or None
    confidence: float
    method: Literal["exact", "alias", "fuzzy", "heuristic", "manual"]
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
    # Mapping of target canonical field -> source column name
    # e.g. {"date": "Txn Date", "description": "Particulars", "debit": "Dr Amount", "credit": "Cr Amount"}
    mappings: Dict[str, str]
    currency: str = "INR"
    account_number: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    file_id: str
    filename: str
    status: str
    parser_type: Optional[str] = None
    total_rows: int = 0
    valid_rows: int = 0
    warning_rows: int = 0
    error_rows: int = 0
    created_at: str
    completed_at: Optional[str] = None


class ParseExecutionResponse(BaseModel):
    job_id: str
    status: str
    total_rows: int
    valid_rows: int
    warning_rows: int
    error_rows: int
    transactions_preview: List[CanonicalTransaction] = Field(default_factory=list)
    errors: List[ParseErrorDetail] = Field(default_factory=list)
