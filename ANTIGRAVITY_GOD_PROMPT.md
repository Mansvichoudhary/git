# ANTIGRAVITY GOD PROMPT: FINAGENT (PART 1 — DATA INGESTION & PARSE ENGINE)

> **Copy-paste this prompt into AntiGravity or any Agentic AI to build the entire production-grade Part 1 Data Ingestion & Parse Engine in one single execution.**

---

```markdown
You are an elite Senior Financial Systems Architect and Full-Stack Principal Engineer building Part 1 of "FinAgent": Automated Bank Statement Reconciliation & Anomaly Investigation Agent.

Your mission is to build the COMPLETE, PRODUCTION-READY, FULLY FUNCTIONAL "Part 1: Data Ingestion & Parse Engine". Do not output placeholders, stub comments, or TODOs. Build the complete backend, the complete parser modules, the complete database models, the complete REST API, tests, synthetic bank statement fixtures, and a polished frontend UI.

================================================================================
CARDINAL RULES & NON-NEGOTIABLE ARCHITECTURAL PRINCIPLES
================================================================================
1. DETERMINISTIC PARSING ONLY:
   - Financial arithmetic, currency parsing, date normalization, debit/credit assignment, and row validation MUST be 100% deterministic (Python, Pandas, regex, OpenPyXL, PyMuPDF, RapidFuzz).
   - Generative LLMs MUST NEVER be used for basic parsing, calculating amounts, or guessing financial numbers. AI may only be invoked as a fallback for ambiguous column schema mapping if deterministic heuristics score < 85%.

2. STRICT CANONICAL CONTRACT:
   - Every input format (CSV, XLSX, Text PDF, Scanned PDF via OCR) from any bank (HDFC, ICICI, SBI, Chase, Barclays, etc.) MUST produce the exact same Canonical Transaction JSON schema. Part 2 (Reconciliation Engine) depends directly on this contract.

3. ZERO SILENT DATA LOSS:
   - Never drop invalid or malformed rows silently. Malformed rows must be logged in a dedicated ParseError table with line number, column, raw value, severity (WARNING vs ERROR), and reason.

4. DUAL DESCRIPTION PROVENANCE:
   - Always preserve both `description_original` (verbatim raw text for AI forensic investigation) and `description_normalized` (cleaned, trimmed whitespace).

================================================================================
REQUIRED CANONICAL TRANSACTION SCHEMA (Pydantic v2)
================================================================================
```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date
from decimal import Decimal

class CanonicalTransaction(BaseModel):
    id: str = Field(description="Deterministic hash ID (e.g. TXN_7F8A1B9C2D3E4F01)")
    date: date = Field(description="ISO 8601 formatted date (YYYY-MM-DD)")
    description: str = Field(description="Cleaned, normalized description")
    description_original: str = Field(description="Verbatim raw narration from source")
    amount: Decimal = Field(description="Positive decimal value, 2 decimal places")
    type: Literal["DEBIT", "CREDIT"] = Field(description="Transaction direction")
    reference: Optional[str] = Field(default=None, description="UTR, Cheque number, or Ref ID")
    balance: Optional[Decimal] = Field(default=None, description="Running balance if provided")
    currency: str = Field(default="INR", description="ISO currency code (default: INR)")
    source_row: Optional[int] = Field(default=None, description="1-indexed row number in source file")
```

================================================================================
THE 7-STAGE PIPELINE TO IMPLEMENT
================================================================================
Stage 1: File Upload & Security Verification
- Support: CSV, TSV, XLSX, XLS, PDF.
- File size limit (25MB), filename path-traversal sanitization, SHA-256 computation for audit trail.

Stage 2: File Type Detection
- Sniff magic bytes (e.g. `%PDF-` vs `PK\x03\x04` vs plaintext).
- For PDFs: inspect text layer density to classify as `PDF_TEXT` or `PDF_OCR`.

Stage 3: Raw Data Extraction
- CSV: Automatic detection of header offset row (handles 5-10 lines of bank account header metadata before the actual transaction table). Sniff delimiter (`,`, `;`, `\t`, `|`).
- XLSX: Detect active sheet with transactions, strip non-tabular header rows.
- PDF: PyMuPDF / pdfplumber table extraction preserving multi-line narrations.
- OCR: Fallback OCR pipeline for scanned statements.

Stage 4: Intelligent Column / Schema Mapping
- Target Canonical Fields: `date`, `description`, `debit`, `credit`, `amount`, `type`, `reference`, `balance`.
- 3-tier mapping resolution:
  1. Exact alias dictionary (e.g., "Txn Date", "Posting Date", "Narration", "Dr Amount", "Cr Amount", "UTR", "Chq No").
  2. RapidFuzz token similarity (threshold >= 85%).
  3. Column value heuristic inference (dates, decimals, indicators).
- Return mapping confidence score. If < 85%, mark state `NEEDS_REVIEW` and provide manual mapping override endpoint.

Stage 5: Deterministic Data Normalization
- Dates: Normalize any format (DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-Mon-YYYY) to ISO `YYYY-MM-DD`.
- Amounts: Strip currency symbols (`₹`, `$`, `€`, `INR`), remove thousands commas (`1,50,000.00` -> `150000.00`), preserve exact decimal cents.
- Debit/Credit logic:
  - Separate columns: Debit filled -> `DEBIT`, Credit filled -> `CREDIT`.
  - Single signed amount: Negative -> `DEBIT`, Positive -> `CREDIT`.
  - Type indicator: `DR` / `CR` column mapped appropriately.
- Descriptions: Trim leading/trailing whitespace, collapse internal whitespace, preserve original in `description_original`.

Stage 6: Strict Business Validation & Error Logging
- Validate date existence & calendar plausibility (1990 <= year <= 2099).
- Validate amount > 0.
- Classify issues:
  - `WARNING`: Missing reference/UTR, unusual whitespace.
  - `ERROR`: Invalid/unparseable date, non-numeric amount, negative amount in debit column.
  - `FATAL`: Corrupt file, password protected PDF.
- Record every failed row into `parse_errors` database table.

Stage 7: Canonical Transaction Output & Persistence
- Generate deterministic transaction ID: `SHA256(account + date + amount + type + reference + description)[:16]`.
- Store valid transactions in `transactions` table.
- Output final Canonical Transaction JSON package ready for Part 2 Reconciliation Engine.

================================================================================
REQUIRED REPOSITORY STRUCTURE
================================================================================
```
FinAgent/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # FastAPI entrypoint, CORS, exception handlers
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py               # Settings (storage path, upload limits)
│   │   │   └── database.py             # SQLite / SQLAlchemy async engine & session
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── ingestion.py            # DB models: File, ParseJob, Transaction, ParseError
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── transaction.py          # CanonicalTransaction, BatchOutput
│   │   │   └── ingestion.py            # UploadResponse, MappingRequest, JobStatusResponse
│   │   ├── parser/
│   │   │   ├── __init__.py
│   │   │   ├── detector.py             # Magic byte & MIME detector, PDF text vs OCR check
│   │   │   ├── csv_parser.py           # Header offset sniffing, delimiter detection, CSV extractor
│   │   │   ├── xlsx_parser.py          # Excel openpyxl tabular extractor
│   │   │   ├── pdf_parser.py           # PyMuPDF / pdfplumber multi-line tabular extractor
│   │   │   ├── mapper.py               # Alias bank + RapidFuzz similarity + heuristic classifier
│   │   │   ├── normalizer.py           # Date, Amount, Debit/Credit, Description normalizer
│   │   │   └── validator.py            # Strict business rules, error classifier
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── ingestion_service.py    # Pipeline orchestrator managing states and DB
│   │   └── api/
│   │       ├── __init__.py
│   │       └── routes_ingestion.py     # Clean REST endpoints
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_parsers.py             # Unit tests for CSV, XLSX, PDF
│   │   ├── test_mapper.py              # Tests for alias and fuzzy column matching
│   │   ├── test_normalizer.py          # Tests for dates, Indian amounts, Dr/Cr
│   │   └── fixtures/                   # Sample bank statements (HDFC, ICICI, SBI)
│   ├── requirements.txt
│   └── run.py                          # Single-command backend runner
├── frontend/                           # Modern, responsive UI
│   ├── index.html                      # Standalone interactive dashboard or Next.js app
│   └── ...
└── FinAgent_Data_Ingestion_Parse_Engine.md
```

================================================================================
REQUIRED API ENDPOINTS
================================================================================
- `POST /api/v1/files/upload`: Upload file, returns `file_id` and `job_id`.
- `POST /api/v1/parse-jobs/{job_id}/detect`: Sniffs format, extracts headers, infers column mapping.
- `POST /api/v1/parse-jobs/{job_id}/map-columns`: Accepts user-confirmed or adjusted column mapping.
- `POST /api/v1/parse-jobs/{job_id}/execute`: Executes normalization, validation, and database storage.
- `GET  /api/v1/parse-jobs/{job_id}/status`: Real-time pipeline state, total/valid/error/warning counts.
- `GET  /api/v1/parse-jobs/{job_id}/transactions`: Paginated canonical transactions list with filtering.
- `GET  /api/v1/parse-jobs/{job_id}/errors`: Full audit error queue with row numbers and exact reasons.
- `GET  /api/v1/parse-jobs/{job_id}/export/canonical-json`: Direct export of canonical JSON payload for Part 2.

================================================================================
DELIVERABLES & EXECUTION INSTRUCTIONS
================================================================================
1. Write clean, modular, production-grade Python code with complete type annotations.
2. Ensure all 7 pipeline stages work seamlessly end-to-end.
3. Include realistic mock/synthetic bank statements (Indian bank formats with headers like 'Txn Date', 'Particulars', 'Dr Amount', 'Cr Amount', 'Balance', 'Chq/Ref No') to prove the parser works immediately.
4. Provide a rich, interactive, and responsive web interface that showcases:
   - File drag-and-drop with size/type validation.
   - Live visual stage tracker (Uploaded -> Detecting -> Extracting -> Mapping -> Normalizing -> Validating -> Complete).
   - Column Mapping inspector with confidence badges and manual correction dropdowns.
   - Real-time row audit stats (Total, Valid, Warnings, Errors).
   - Interactive transaction data table with search, debit/credit badges, and export button.
   - Expandable Error Log drawer displaying flagged rows with exact line numbers and reasons.
5. Provide comprehensive automated unit tests covering all edge cases (multi-line narrations, missing references, commas in currency, mixed date formats).
6. Verify everything by running the tests and serving the application.
```
