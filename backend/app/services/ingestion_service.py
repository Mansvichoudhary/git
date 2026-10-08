import json
import uuid
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from app.core.config import UPLOAD_DIR, MAX_FILE_SIZE_BYTES, ALLOWED_EXTENSIONS
from app.core.database import get_db_connection
from app.parser.detector import detect_file_format
from app.parser.csv_parser import parse_csv_file
from app.parser.xlsx_parser import parse_xlsx_file
from app.parser.pdf_parser import parse_pdf_file
from app.parser.mapper import infer_column_mappings
from app.parser.validator import validate_and_build_canonical_transaction
from app.schemas.transaction import CanonicalTransaction, ParseErrorDetail, CanonicalStatementPackage


class IngestionService:

    @staticmethod
    def create_upload_job(filename: str, file_bytes: bytes) -> Dict[str, Any]:
        """
        Validates, hashes, stores the uploaded file, and initializes DB records.
        """
        # Security sanitization
        safe_filename = Path(filename).name
        ext = Path(safe_filename).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size exceeds maximum permitted limit of 25 MB.")

        file_id = f"FILE_{uuid.uuid4().hex[:12].upper()}"
        job_id = f"JOB_{uuid.uuid4().hex[:12].upper()}"
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        stored_filename = f"{file_id}_{safe_filename}"
        storage_path = UPLOAD_DIR / stored_filename
        with open(storage_path, "wb") as f:
            f.write(file_bytes)

        detection = detect_file_format(storage_path)

        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO files (id, filename, mime_type, file_size, storage_path, sha256_hash, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, safe_filename, detection["mime_type"], len(file_bytes), str(storage_path), sha256, "UPLOADED")
            )
            conn.execute(
                """
                INSERT INTO parse_jobs (id, file_id, status, parser_type)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, file_id, "UPLOADED", detection["file_type"])
            )
        conn.close()

        return {
            "file_id": file_id,
            "job_id": job_id,
            "filename": safe_filename,
            "file_size": len(file_bytes),
            "mime_type": detection["mime_type"],
            "sha256_hash": sha256,
            "status": "UPLOADED"
        }

    @staticmethod
    def extract_raw_records(job_id: str) -> Tuple[str, List[str], List[Dict[str, Any]], Path]:
        """
        Extracts raw unmapped records based on the file type.
        """
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT f.storage_path, j.parser_type 
            FROM parse_jobs j 
            JOIN files f ON j.file_id = f.id 
            WHERE j.id = ?
            """,
            (job_id,)
        ).fetchone()
        conn.close()

        if not row:
            raise ValueError(f"Job ID '{job_id}' not found.")

        storage_path = Path(row["storage_path"])
        parser_type = row["parser_type"]

        if parser_type == "CSV":
            _, headers, raw_rows = parse_csv_file(storage_path)
        elif parser_type == "XLSX":
            _, headers, raw_rows = parse_xlsx_file(storage_path)
        elif "PDF" in parser_type:
            _, headers, raw_rows = parse_pdf_file(storage_path)
        else:
            raise ValueError(f"Unsupported parser type: {parser_type}")

        return parser_type, headers, raw_rows, storage_path

    @classmethod
    def detect_and_suggest_mappings(cls, job_id: str) -> Dict[str, Any]:
        """
        Runs stage 2-4: format detection, table extraction, and column inference.
        """
        parser_type, headers, raw_rows, _ = cls.extract_raw_records(job_id)

        mappings, confidence = infer_column_mappings(headers, raw_rows)
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

    @classmethod
    def execute_pipeline(
        cls,
        job_id: str,
        custom_mappings: Optional[Dict[str, str]] = None,
        account_number: str = "DEFAULT_ACC",
        currency: str = "INR"
    ) -> Dict[str, Any]:
        """
        Runs Stage 5-7: Normalization, validation, persistence, and canonical package preparation.
        """
        parser_type, headers, raw_rows, _ = cls.extract_raw_records(job_id)

        # Build column mapping dictionary (target_field -> source_column)
        active_mapping: Dict[str, str] = {}
        if custom_mappings:
            active_mapping = custom_mappings
        else:
            suggested, _ = infer_column_mappings(headers, raw_rows)
            for m in suggested:
                if m.target_field:
                    active_mapping[m.target_field] = m.source_column

        valid_transactions: List[CanonicalTransaction] = []
        all_errors: List[ParseErrorDetail] = []
        warning_count = 0
        error_count = 0

        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE parse_jobs SET status = 'NORMALIZING', started_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            # Clear any previous run transactions/errors
            conn.execute("DELETE FROM transactions WHERE parse_job_id = ?", (job_id,))
            conn.execute("DELETE FROM parse_errors WHERE parse_job_id = ?", (job_id,))

            for idx, raw_row in enumerate(raw_rows, start=1):
                canonical_txn, row_errors = validate_and_build_canonical_transaction(
                    raw_row=raw_row,
                    row_number=idx,
                    column_mapping=active_mapping,
                    account_number=account_number,
                    currency=currency
                )

                for err in row_errors:
                    all_errors.append(err)
                    err_id = f"ERR_{uuid.uuid4().hex[:10].upper()}"
                    conn.execute(
                        """
                        INSERT INTO parse_errors (id, parse_job_id, row_number, field, raw_value, severity, message)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (err_id, job_id, err.row_number, err.field, err.raw_value, err.severity, err.message)
                    )
                    if err.severity == "WARNING":
                        warning_count += 1
                    else:
                        error_count += 1

                if canonical_txn:
                    valid_transactions.append(canonical_txn)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO transactions (id, parse_job_id, date, description, description_original, amount, type, reference, balance, currency, source_row)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{job_id}_{canonical_txn.id}",
                            job_id,
                            canonical_txn.date.isoformat(),
                            canonical_txn.description,
                            canonical_txn.description_original,
                            float(canonical_txn.amount),
                            canonical_txn.type,
                            canonical_txn.reference,
                            float(canonical_txn.balance) if canonical_txn.balance else None,
                            canonical_txn.currency,
                            canonical_txn.source_row
                        )
                    )

            conn.execute(
                """
                UPDATE parse_jobs 
                SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP,
                    total_rows = ?, valid_rows = ?, warning_rows = ?, error_rows = ?,
                    mapping_config = ?
                WHERE id = ?
                """,
                (len(raw_rows), len(valid_transactions), warning_count, error_count, json.dumps(active_mapping), job_id)
            )

        conn.close()

        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "total_rows": len(raw_rows),
            "valid_rows": len(valid_transactions),
            "warning_rows": warning_count,
            "error_rows": error_count,
            "transactions_preview": valid_transactions[:10],
            "errors": all_errors[:10]
        }

    @staticmethod
    def get_job_status(job_id: str) -> Dict[str, Any]:
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT j.*, f.filename 
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
            txns.append(CanonicalTransaction(
                id=t["id"],
                date=datetime.strptime(t["date"], "%Y-%m-%d").date(),
                description=t["description"],
                description_original=t["description_original"],
                amount=t["amount"],
                type=t["type"],
                reference=t["reference"],
                balance=t["balance"],
                currency=t["currency"],
                source_row=t["source_row"]
            ))

        errs = [ParseErrorDetail(
            row_number=e["row_number"],
            field=e["field"],
            raw_value=e["raw_value"],
            severity=e["severity"],
            message=e["message"]
        ) for e in raw_errs]

        return CanonicalStatementPackage(
            statement_id=f"STMT_{job['id']}",
            filename=job["filename"],
            file_type=job["parser_type"] or "UNKNOWN",
            sha256_hash=job.get("file_id", ""),
            total_rows=job["total_rows"],
            valid_rows=job["valid_rows"],
            warning_count=job["warning_rows"],
            error_count=job["error_rows"],
            currency="INR",
            transactions=txns,
            errors=errs
        )
