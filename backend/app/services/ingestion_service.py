import json
import uuid
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import UPLOAD_DIR, MAX_FILE_SIZE_BYTES, ALLOWED_EXTENSIONS
from app.core.database import get_db_connection
from app.parser.detector import detect_file_format
from app.parser.extractor import extract_raw_tabular_data
from app.parser.mapper import infer_column_mappings
from app.parser.validator import validate_and_build_canonical_transaction
from app.schemas.transaction import (
    CanonicalTransaction,
    ParseErrorDetail,
    CanonicalStatementPackage,
    ControlTotalsSummary
)
from app.schemas.ingestion import (
    CompanyCreate,
    CompanyResponse,
    ReconciliationCreate,
    ReconciliationResponse,
    SourceCreate,
    SourceResponse,
    ColumnMappingItem
)


class IngestionService:

    # -------------------------------------------------------------
    # Multi-Tenant Company Management (Section 5)
    # -------------------------------------------------------------
    @staticmethod
    def create_company(comp: CompanyCreate) -> CompanyResponse:
        conn = get_db_connection()
        comp_id = f"COMP_{uuid.uuid4().hex[:8].upper()}"
        with conn:
            conn.execute(
                """
                INSERT INTO companies (id, company_name, legal_name, industry, email, phone, address, country, timezone, base_currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    comp_id, comp.company_name, comp.legal_name, comp.industry,
                    comp.email, comp.phone, comp.address, comp.country,
                    comp.timezone, comp.base_currency
                )
            )
            # Add owner role
            conn.execute(
                """
                INSERT INTO company_members (id, company_id, user_id, role)
                VALUES (?, ?, ?, ?)
                """,
                (f"MBR_{uuid.uuid4().hex[:8].upper()}", comp_id, "default_user", "OWNER")
            )
        conn.close()
        return IngestionService.get_company(comp_id)

    @staticmethod
    def get_companies() -> List[CompanyResponse]:
        conn = get_db_connection()
        rows = conn.execute("SELECT * FROM companies ORDER BY created_at DESC").fetchall()
        conn.close()
        return [CompanyResponse(**dict(r)) for r in rows]

    @staticmethod
    def get_company(company_id: str) -> CompanyResponse:
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        conn.close()
        if not row:
            raise ValueError(f"Company '{company_id}' not found.")
        return CompanyResponse(**dict(row))

    # -------------------------------------------------------------
    # Reconciliation & Financial Source Context (Sections 6 & 7)
    # -------------------------------------------------------------
    @staticmethod
    def create_reconciliation(rec: ReconciliationCreate) -> ReconciliationResponse:
        conn = get_db_connection()
        rec_id = f"REC_{uuid.uuid4().hex[:8].upper()}"
        with conn:
            conn.execute(
                """
                INSERT INTO reconciliations (id, company_id, name, period_start, period_end, status)
                VALUES (?, ?, ?, ?, ?, 'INGESTING')
                """,
                (rec_id, rec.company_id, rec.name, rec.period_start, rec.period_end)
            )
        conn.close()
        return IngestionService.get_reconciliation(rec_id)

    @staticmethod
    def get_reconciliations(company_id: Optional[str] = None) -> List[ReconciliationResponse]:
        conn = get_db_connection()
        if company_id:
            rows = conn.execute("SELECT * FROM reconciliations WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM reconciliations ORDER BY created_at DESC").fetchall()
        conn.close()
        return [ReconciliationResponse(**dict(r)) for r in rows]

    @staticmethod
    def get_reconciliation(rec_id: str) -> ReconciliationResponse:
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM reconciliations WHERE id = ?", (rec_id,)).fetchone()
        conn.close()
        if not row:
            raise ValueError(f"Reconciliation '{rec_id}' not found.")
        return ReconciliationResponse(**dict(row))

    @staticmethod
    def create_source(src: SourceCreate) -> SourceResponse:
        conn = get_db_connection()
        src_id = f"SRC_{uuid.uuid4().hex[:8].upper()}"
        with conn:
            conn.execute(
                """
                INSERT INTO sources (id, reconciliation_id, source_type, name, status)
                VALUES (?, ?, ?, ?, 'ACTIVE')
                """,
                (src_id, src.reconciliation_id, src.source_type, src.name)
            )
        conn.close()
        return SourceResponse(
            id=src_id,
            reconciliation_id=src.reconciliation_id,
            source_type=src.source_type,
            name=src.name,
            status="ACTIVE",
            created_at=datetime.now(timezone.utc).isoformat()
        )

    @staticmethod
    def get_sources(reconciliation_id: str) -> List[SourceResponse]:
        conn = get_db_connection()
        rows = conn.execute("SELECT * FROM sources WHERE reconciliation_id = ? ORDER BY created_at ASC", (reconciliation_id,)).fetchall()
        conn.close()
        return [SourceResponse(**dict(r)) for r in rows]

    # -------------------------------------------------------------
    # Upload, Deduplication, & Extraction Pipeline (Sections 8, 9, 10, 13)
    # -------------------------------------------------------------
    @staticmethod
    def create_upload_job(
        filename: str,
        file_bytes: bytes,
        reconciliation_id: str = "REC_DEMO_01",
        source_id: str = "SRC_DEMO_BANK",
        source_type: str = "BANK_STATEMENT"
    ) -> Dict[str, Any]:
        """
        Validates format, checks SHA-256 duplicate fingerprint within scope,
        and creates files + parse_jobs records.
        """
        safe_filename = Path(filename).name
        ext = Path(safe_filename).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size exceeds maximum permitted limit of 25 MB.")

        sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Check for duplicate file within this reconciliation context (Section 9)
        conn = get_db_connection()
        existing_file = conn.execute(
            "SELECT * FROM files WHERE reconciliation_id = ? AND file_hash = ? LIMIT 1",
            (reconciliation_id, sha256)
        ).fetchone()

        is_duplicate = False
        if existing_file:
            is_duplicate = True

        file_id = f"FILE_{uuid.uuid4().hex[:12].upper()}"
        job_id = f"JOB_{uuid.uuid4().hex[:12].upper()}"

        stored_filename = f"{file_id}_{safe_filename}"
        storage_path = UPLOAD_DIR / stored_filename
        with open(storage_path, "wb") as f:
            f.write(file_bytes)

        detection = detect_file_format(storage_path)

        with conn:
            conn.execute(
                """
                INSERT INTO files (id, source_id, reconciliation_id, filename, mime_type, file_size, file_hash, storage_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'UPLOADED')
                """,
                (file_id, source_id, reconciliation_id, safe_filename, detection["mime_type"], len(file_bytes), sha256, str(storage_path))
            )
            conn.execute(
                """
                INSERT INTO parse_jobs (id, file_id, status, parser_type, parser_version)
                VALUES (?, ?, 'UPLOADED', ?, '1.0.0')
                """,
                (job_id, file_id, detection["file_type"])
            )
        conn.close()

        return {
            "file_id": file_id,
            "job_id": job_id,
            "reconciliation_id": reconciliation_id,
            "source_id": source_id,
            "source_type": source_type,
            "filename": safe_filename,
            "file_size": len(file_bytes),
            "mime_type": detection["mime_type"],
            "sha256_hash": sha256,
            "is_duplicate": is_duplicate,
            "status": "UPLOADED"
        }

    @staticmethod
    def extract_raw_records(job_id: str) -> Tuple[str, List[str], List[Dict[str, Any]], Path, Dict[str, Any]]:
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT f.id as file_id, f.filename, f.storage_path, f.source_id, f.reconciliation_id, j.parser_type 
            FROM parse_jobs j 
            JOIN files f ON j.file_id = f.id 
            WHERE j.id = ?
            """,
            (job_id,)
        ).fetchone()
        conn.close()

        if not row:
            raise ValueError(f"Job ID '{job_id}' not found.")

        meta = dict(row)
        storage_path = Path(meta["storage_path"])
        parser_type = meta["parser_type"] or "CSV"

        _, headers, raw_rows = extract_raw_tabular_data(storage_path, parser_type)
        return parser_type, headers, raw_rows, storage_path, meta

    # -------------------------------------------------------------
    # Schema Mapping & Persistent Memory (Sections 15 & 16)
    # -------------------------------------------------------------
    @classmethod
    def detect_and_suggest_mappings(cls, job_id: str) -> Dict[str, Any]:
        parser_type, headers, raw_rows, _, meta = cls.extract_raw_records(job_id)

        # Check persistent mapping rules first (Section 16)
        conn = get_db_connection()
        source_id = meta.get("source_id") or "SRC_DEMO_BANK"
        source_row = conn.execute("SELECT source_type FROM sources WHERE id = ?", (source_id,)).fetchone()
        source_type = source_row["source_type"] if source_row else "BANK_STATEMENT"

        learned_rules = conn.execute(
            "SELECT source_column, target_field, confidence FROM mapping_rules WHERE source_type = ?",
            (source_type,)
        ).fetchall()
        conn.close()

        learned_dict = {r["source_column"].lower().strip(): (r["target_field"], r["confidence"]) for r in learned_rules}

        mappings, confidence = infer_column_mappings(headers, raw_rows)

        # Overlay learned rules
        for m in mappings:
            col_key = m.source_column.lower().strip()
            if col_key in learned_dict:
                m.target_field = learned_dict[col_key][0]
                m.confidence = max(m.confidence, learned_dict[col_key][1])
                m.method = "learned"

        status = "READY_FOR_EXECUTION" if confidence >= 0.85 else "NEEDS_REVIEW"

        conn = get_db_connection()
        with conn:
            conn.execute(
                "UPDATE parse_jobs SET status = ?, total_rows = ? WHERE id = ?",
                (status, len(raw_rows), job_id)
            )
        conn.close()

        return {
            "job_id": job_id,
            "file_type": parser_type,
            "header_row_index": 0,
            "detected_headers": headers,
            "suggested_mappings": mappings,
            "confidence_score": confidence,
            "status": status,
            "sample_rows": raw_rows[:5]
        }

    # -------------------------------------------------------------
    # Normalization, Validation, & Control Totals (Sections 17, 18, 19)
    # -------------------------------------------------------------
    @classmethod
    def execute_pipeline(
        cls,
        job_id: str,
        custom_mappings: Optional[Dict[str, str]] = None,
        account_number: str = "DEFAULT_ACC",
        currency: str = "INR",
        source_type: str = "BANK_STATEMENT",
        remember_rules: bool = True
    ) -> Dict[str, Any]:
        parser_type, headers, raw_rows, _, meta = cls.extract_raw_records(job_id)

        # Active mapping dictionary (target_field -> source_column)
        active_mapping: Dict[str, str] = {}
        if custom_mappings:
            active_mapping = custom_mappings
        else:
            suggested, _ = infer_column_mappings(headers, raw_rows)
            for m in suggested:
                if m.target_field:
                    active_mapping[m.target_field] = m.source_column

        # Persistent Learning: Save manual mappings for future reuse (Section 16)
        if remember_rules and active_mapping:
            conn = get_db_connection()
            with conn:
                for target_f, source_c in active_mapping.items():
                    rule_id = f"RULE_{uuid.uuid4().hex[:8].upper()}"
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO mapping_rules (id, source_type, source_column, target_field, confidence)
                        VALUES (?, ?, ?, ?, 1.0)
                        """,
                        (rule_id, source_type, source_c, target_f)
                    )
            conn.close()

        valid_transactions: List[CanonicalTransaction] = []
        all_errors: List[ParseErrorDetail] = []
        warning_count = 0
        error_count = 0

        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")
        opening_balance: Optional[Decimal] = None
        closing_balance: Optional[Decimal] = None

        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE parse_jobs SET status = 'NORMALIZING', started_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            conn.execute("DELETE FROM transactions WHERE parse_job_id = ?", (job_id,))
            conn.execute("DELETE FROM parse_errors WHERE parse_job_id = ?", (job_id,))

            file_id = meta.get("file_id", "FILE_UNKNOWN")
            filename = meta.get("filename", "unknown.file")
            rec_id = meta.get("reconciliation_id", "REC_DEMO_01")
            src_id = meta.get("source_id", "SRC_DEMO_BANK")

            for idx, raw_row in enumerate(raw_rows, start=1):
                # Provenance dictionary (Section 22)
                row_provenance = {
                    "file_id": file_id,
                    "filename": filename,
                    "page": 1,
                    "row": idx
                }

                canonical_txn, row_errors = validate_and_build_canonical_transaction(
                    raw_row=raw_row,
                    row_number=idx,
                    column_mapping=active_mapping,
                    account_number=account_number,
                    currency=currency,
                    reconciliation_id=rec_id,
                    source_id=src_id,
                    source_type=source_type,
                    provenance=row_provenance,
                    page_number=1
                )

                for err in row_errors:
                    all_errors.append(err)
                    err_id = f"ERR_{uuid.uuid4().hex[:10].upper()}"
                    conn.execute(
                        """
                        INSERT INTO parse_errors (id, parse_job_id, row_number, page_number, field, value, severity, message)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (err_id, job_id, err.row_number, err.page_number, err.field, err.raw_value, err.severity, err.message)
                    )
                    if err.severity == "WARNING":
                        warning_count += 1
                    else:
                        error_count += 1

                if canonical_txn:
                    valid_transactions.append(canonical_txn)

                    # Accumulate control totals (Section 19)
                    if canonical_txn.type == "DEBIT":
                        total_debits += canonical_txn.amount
                    else:
                        total_credits += canonical_txn.amount

                    if opening_balance is None and canonical_txn.balance is not None:
                        # Infer opening balance prior to first transaction
                        if canonical_txn.type == "DEBIT":
                            opening_balance = canonical_txn.balance + canonical_txn.amount
                        else:
                            opening_balance = canonical_txn.balance - canonical_txn.amount

                    if canonical_txn.balance is not None:
                        closing_balance = canonical_txn.balance

                    conn.execute(
                        """
                        INSERT OR REPLACE INTO transactions (
                            id, reconciliation_id, source_id, source_type, parse_job_id,
                            date, description, description_original, amount, type, reference,
                            balance, currency, account_id, provenance, source_row
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{job_id}_{canonical_txn.id}",
                            rec_id,
                            src_id,
                            source_type,
                            job_id,
                            canonical_txn.date.isoformat(),
                            canonical_txn.description,
                            canonical_txn.description_original,
                            float(canonical_txn.amount),
                            canonical_txn.type,
                            canonical_txn.reference,
                            float(canonical_txn.balance) if canonical_txn.balance else None,
                            canonical_txn.currency,
                            canonical_txn.account_id,
                            json.dumps(canonical_txn.provenance),
                            canonical_txn.source_row
                        )
                    )

            # Financial Control Totals Verification (Section 19)
            control_status = "NOT_APPLICABLE"
            expected_closing = None
            control_diff = Decimal("0.00")

            if opening_balance is not None and closing_balance is not None:
                expected_closing = opening_balance + total_credits - total_debits
                control_diff = closing_balance - expected_closing
                control_status = "VERIFIED" if abs(control_diff) < Decimal("0.01") else "CONTROL_TOTAL_MISMATCH"

            conn.execute(
                """
                UPDATE parse_jobs 
                SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP,
                    total_rows = ?, valid_rows = ?, warning_rows = ?, error_rows = ?,
                    opening_balance = ?, closing_balance = ?, total_debits = ?, total_credits = ?,
                    control_difference = ?, control_status = ?, mapping_config = ?
                WHERE id = ?
                """,
                (
                    len(raw_rows), len(valid_transactions), warning_count, error_count,
                    float(opening_balance) if opening_balance else None,
                    float(closing_balance) if closing_balance else None,
                    float(total_debits), float(total_credits),
                    float(control_diff), control_status,
                    json.dumps(active_mapping), job_id
                )
            )

        conn.close()

        control_summary = ControlTotalsSummary(
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            total_debits=total_debits,
            total_credits=total_credits,
            transaction_count=len(valid_transactions),
            expected_closing_balance=expected_closing,
            control_difference=control_diff,
            status=control_status
        )

        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "total_rows": len(raw_rows),
            "valid_rows": len(valid_transactions),
            "warning_rows": warning_count,
            "error_rows": error_count,
            "control_totals": control_summary,
            "transactions_preview": valid_transactions[:10],
            "errors": all_errors[:10]
        }

    # -------------------------------------------------------------
    # Recovery, Queries, & Canonical Package Export (Sections 20, 26, 27)
    # -------------------------------------------------------------
    @staticmethod
    def retry_job(job_id: str) -> Dict[str, Any]:
        """
        Stage-level retry for recovery without discarding file metadata (Section 26).
        """
        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE parse_jobs SET status = 'UPLOADED', started_at = NULL, completed_at = NULL WHERE id = ?", (job_id,))
        conn.close()
        return IngestionService.detect_and_suggest_mappings(job_id)

    @staticmethod
    def get_job_status(job_id: str) -> Dict[str, Any]:
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT j.*, f.filename, f.source_id, f.reconciliation_id 
            FROM parse_jobs j 
            JOIN files f ON j.file_id = f.id 
            WHERE j.id = ?
            """,
            (job_id,)
        ).fetchone()
        conn.close()
        if not row:
            raise ValueError(f"Job '{job_id}' not found")
        return dict(row)

    @staticmethod
    def get_transactions(job_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT * FROM transactions 
            WHERE parse_job_id = ? 
            ORDER BY source_row ASC 
            LIMIT ? OFFSET ?
            """,
            (job_id, limit, offset)
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            if d["id"].startswith(f"{job_id}_"):
                d["id"] = d["id"][len(f"{job_id}_"):]
            if d.get("provenance") and isinstance(d["provenance"], str):
                try:
                    d["provenance"] = json.loads(d["provenance"])
                except Exception:
                    pass
            results.append(d)
        return results

    @staticmethod
    def get_errors(job_id: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT * FROM parse_errors 
            WHERE parse_job_id = ? 
            ORDER BY row_number ASC
            """,
            (job_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @classmethod
    def export_canonical_statement_package(cls, job_id: str) -> CanonicalStatementPackage:
        job = cls.get_job_status(job_id)
        raw_txns = cls.get_transactions(job_id, limit=50000)
        raw_errs = cls.get_errors(job_id)

        txns: List[CanonicalTransaction] = []
        for t in raw_txns:
            prov = t.get("provenance") or {}
            txns.append(CanonicalTransaction(
                id=t["id"],
                reconciliation_id=t.get("reconciliation_id", "REC_DEMO_01"),
                source_id=t.get("source_id", "SRC_DEMO_BANK"),
                source_type=t.get("source_type", "BANK_STATEMENT"),
                date=datetime.strptime(t["date"], "%Y-%m-%d").date(),
                description=t["description"],
                description_original=t["description_original"],
                amount=t["amount"],
                type=t["type"],
                reference=t["reference"],
                balance=t["balance"],
                currency=t["currency"],
                account_id=t.get("account_id"),
                provenance=prov,
                source_row=t["source_row"]
            ))

        errs = [ParseErrorDetail(
            row_number=e["row_number"],
            page_number=e.get("page_number", 1),
            field=e["field"],
            raw_value=e["value"],
            severity=e["severity"],
            message=e["message"]
        ) for e in raw_errs]

        opening_b = Decimal(str(job["opening_balance"])) if job["opening_balance"] is not None else None
        closing_b = Decimal(str(job["closing_balance"])) if job["closing_balance"] is not None else None
        debits_b = Decimal(str(job["total_debits"] or 0))
        credits_b = Decimal(str(job["total_credits"] or 0))
        diff_b = Decimal(str(job["control_difference"] or 0))

        control_summary = ControlTotalsSummary(
            opening_balance=opening_b,
            closing_balance=closing_b,
            total_debits=debits_b,
            total_credits=credits_b,
            transaction_count=job["valid_rows"],
            expected_closing_balance=opening_b + credits_b - debits_b if opening_b is not None else None,
            control_difference=diff_b,
            status=job.get("control_status", "NOT_APPLICABLE")
        )

        return CanonicalStatementPackage(
            statement_id=f"STMT_{job['id']}",
            reconciliation_id=job.get("reconciliation_id", "REC_DEMO_01"),
            source_id=job.get("source_id", "SRC_DEMO_BANK"),
            source_type="BANK_STATEMENT",
            account="DEFAULT_ACC",
            currency="INR",
            filename=job["filename"],
            file_type=job["parser_type"] or "UNKNOWN",
            sha256_hash=job.get("file_id", ""),
            total_rows=job["total_rows"],
            valid_rows=job["valid_rows"],
            warning_count=job["warning_rows"],
            error_count=job["error_rows"],
            control_totals=control_summary,
            transactions=txns,
            errors=errs,
            metadata={
                "source_file": job["filename"],
                "parser": (job["parser_type"] or "csv").lower(),
                "total_transactions": job["total_rows"],
                "valid_transactions": job["valid_rows"],
                "control_status": job.get("control_status", "NOT_APPLICABLE"),
                "validation_status": "PASSED" if job["error_rows"] == 0 else "PARTIAL_ERRORS"
            }
        )
