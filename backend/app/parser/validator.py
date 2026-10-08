import hashlib
from typing import Dict, Any, Optional, Tuple, List
from decimal import Decimal
from datetime import date
from app.schemas.transaction import CanonicalTransaction, ParseErrorDetail
from app.parser.normalizer import (
    normalize_date,
    normalize_transaction_type_and_amount,
    normalize_description,
    normalize_reference,
    clean_amount_string
)


def generate_deterministic_id(
    account: str,
    txn_date: date,
    amount: Decimal,
    txn_type: str,
    reference: Optional[str],
    description: str,
    source_row: Optional[int] = None
) -> str:
    """
    Computes a deterministic hash ID for auditability and idempotency.
    SHA-256 hash formatted as TXN_<16-hex-chars>.
    """
    raw_payload = f"{account}|{txn_date.isoformat()}|{amount:.2f}|{txn_type}|{reference or ''}|{description.strip().upper()}|{source_row or ''}"
    hash_digest = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()[:16].upper()
    return f"TXN_{hash_digest}"


def validate_and_build_canonical_transaction(
    raw_row: Dict[str, Any],
    row_number: int,
    column_mapping: Dict[str, str],  # target_field -> source_column
    account_number: str = "DEFAULT_ACC",
    currency: str = "INR"
) -> Tuple[Optional[CanonicalTransaction], List[ParseErrorDetail]]:
    """
    Validates a single raw row against financial business rules.
    Returns (CanonicalTransaction, list_of_errors_or_warnings).
    """
    errors: List[ParseErrorDetail] = []

    # 1. Date Extraction & Validation
    date_col = column_mapping.get("date")
    raw_date = raw_row.get(date_col) if date_col else None
    parsed_date = normalize_date(raw_date)

    if not parsed_date:
        errors.append(ParseErrorDetail(
            row_number=row_number,
            field="date",
            raw_value=str(raw_date),
            severity="ERROR",
            message=f"Missing or unparseable date in column '{date_col}'."
        ))

    # 2. Description Normalization
    desc_col = column_mapping.get("description")
    raw_desc = raw_row.get(desc_col) if desc_col else None
    clean_desc, original_desc = normalize_description(raw_desc)

    if not clean_desc:
        errors.append(ParseErrorDetail(
            row_number=row_number,
            field="description",
            raw_value=str(raw_desc),
            severity="ERROR",
            message=f"Missing or empty transaction narration in column '{desc_col}'."
        ))

    # 3. Amount & Direction (Debit / Credit)
    debit_col = column_mapping.get("debit")
    credit_col = column_mapping.get("credit")
    amount_col = column_mapping.get("amount")
    type_col = column_mapping.get("type")

    amount, txn_type, amount_err = normalize_transaction_type_and_amount(
        debit_val=raw_row.get(debit_col) if debit_col else None,
        credit_val=raw_row.get(credit_col) if credit_col else None,
        amount_val=raw_row.get(amount_col) if amount_col else None,
        type_val=raw_row.get(type_col) if type_col else None,
    )

    if amount_err or amount is None or amount <= 0:
        errors.append(ParseErrorDetail(
            row_number=row_number,
            field="amount",
            raw_value=f"debit={raw_row.get(debit_col)}, credit={raw_row.get(credit_col)}, amount={raw_row.get(amount_col)}",
            severity="ERROR",
            message=amount_err or "Invalid or non-positive transaction amount."
        ))

    # 4. Reference Extraction (Optional with Warning)
    ref_col = column_mapping.get("reference")
    raw_ref = raw_row.get(ref_col) if ref_col else None
    clean_ref = normalize_reference(raw_ref)

    if not clean_ref:
        errors.append(ParseErrorDetail(
            row_number=row_number,
            field="reference",
            raw_value=str(raw_ref),
            severity="WARNING",
            message="Reference / UTR / Cheque number is absent or blank."
        ))

    # 5. Balance Extraction (Optional)
    bal_col = column_mapping.get("balance")
    raw_bal = raw_row.get(bal_col) if bal_col else None
    clean_bal, _ = clean_amount_string(raw_bal)

    # Check for blocking errors
    has_blocking_errors = any(e.severity in ["ERROR", "FATAL"] for e in errors)
    if has_blocking_errors or not parsed_date or not amount or not txn_type:
        return None, errors

    # Generate Canonical Transaction
    txn_id = generate_deterministic_id(
        account=account_number,
        txn_date=parsed_date,
        amount=amount,
        txn_type=txn_type,
        reference=clean_ref,
        description=clean_desc,
        source_row=row_number
    )

    canonical_txn = CanonicalTransaction(
        id=txn_id,
        date=parsed_date,
        description=clean_desc,
        description_original=original_desc,
        amount=amount,
        type=txn_type,
        reference=clean_ref,
        balance=clean_bal,
        currency=currency,
        source_row=row_number
    )

    return canonical_txn, errors
