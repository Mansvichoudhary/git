import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Tuple, Optional, Any


# Common date format patterns
DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y",
    "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y",
    "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d"
]


def normalize_date(raw_val: Any) -> Optional[date]:
    """
    Deterministically normalizes heterogeneous date formats into a datetime.date object.
    Supports Indian formats (DD/MM/YYYY), US formats, and alphanumeric dates (01-Oct-2026).
    """
    if raw_val is None:
        return None
    
    if isinstance(raw_val, (datetime, date)):
        return raw_val if isinstance(raw_val, date) else raw_val.date()
    
    val_str = str(raw_val).strip()
    if not val_str:
        return None

    # Clean extraneous time strings if present (e.g., "01/10/2026 14:30:00")
    val_str = re.sub(r"\s+\d{1,2}:\d{2}(:\d{2})?(\s*(AM|PM|am|pm))?", "", val_str)

    # Try standard formats
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(val_str, fmt).date()
            # Plausibility sanity check
            if 1990 <= parsed.year <= 2099:
                return parsed
        except ValueError:
            continue

    return None


def clean_amount_string(raw_val: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Strips currency symbols (₹, $, €, INR), commas, and detects trailing DR/CR.
    Returns (absolute_decimal_amount, detected_hint_or_direction)
    """
    if raw_val is None:
        return None, None
    
    if isinstance(raw_val, (int, float, Decimal)):
        if str(raw_val).lower() == "nan":
            return None, None
        dec_val = Decimal(str(raw_val))
        return abs(dec_val), "DEBIT" if dec_val < 0 else None

    val_str = str(raw_val).strip()
    if not val_str or val_str.lower() in ["", "-", "nil", "none", "n/a"]:
        return None, None

    direction_hint = None
    upper_val = val_str.upper()

    # Detect Dr / Cr suffix or prefix
    if "DR" in upper_val or "DEBIT" in upper_val:
        direction_hint = "DEBIT"
    elif "CR" in upper_val or "CREDIT" in upper_val:
        direction_hint = "CREDIT"

    # Check for accounting parenthesis negative format: (1,250.00)
    is_parenthesis_negative = False
    if val_str.startswith("(") and val_str.endswith(")"):
        is_parenthesis_negative = True
        direction_hint = "DEBIT"

    # Strip currency symbols, quotes, commas, letters
    cleaned = re.sub(r"[₹\$€£INRinr,\s]", "", val_str)
    cleaned = re.sub(r"[^\d.-]", "", cleaned)

    if not cleaned or cleaned == "-" or cleaned == ".":
        return None, None

    try:
        dec = Decimal(cleaned)
        if is_parenthesis_negative or dec < 0:
            direction_hint = "DEBIT"
            dec = abs(dec)
        return dec.quantize(Decimal("0.01")), direction_hint
    except (InvalidOperation, ValueError):
        return None, None


def normalize_transaction_type_and_amount(
    debit_val: Any,
    credit_val: Any,
    amount_val: Any = None,
    type_val: Any = None
) -> Tuple[Optional[Decimal], Optional[str], Optional[str]]:
    """
    Determines final (amount, type: 'DEBIT'|'CREDIT', error_message).
    Handles:
    - 2-column model (Debit & Credit columns)
    - 1-column signed amount model
    - Amount + Type indicator model
    """
    d_amt, _ = clean_amount_string(debit_val)
    c_amt, _ = clean_amount_string(credit_val)

    # 1. Two-column model (Debit & Credit)
    if d_amt is not None and d_amt > 0 and (c_amt is None or c_amt == 0):
        return d_amt, "DEBIT", None
    
    if c_amt is not None and c_amt > 0 and (d_amt is None or d_amt == 0):
        return c_amt, "CREDIT", None
    
    if d_amt is not None and d_amt > 0 and c_amt is not None and c_amt > 0:
        return None, None, "Ambiguous row: both Debit and Credit have non-zero amounts."

    # 2. Single Amount Column with Type or Sign
    if amount_val is not None:
        a_amt, hint = clean_amount_string(amount_val)
        if a_amt is not None and a_amt > 0:
            if type_val:
                t_str = str(type_val).strip().upper()
                if "DR" in t_str or "DEBIT" in t_str or "WITHDRAWAL" in t_str:
                    return a_amt, "DEBIT", None
                if "CR" in t_str or "CREDIT" in t_str or "DEPOSIT" in t_str:
                    return a_amt, "CREDIT", None
            
            if hint:
                return a_amt, hint, None
            
            # Default fallback for single unsigned amount if no other info
            return a_amt, "DEBIT", None

    return None, None, "No valid transaction amount or debit/credit found."


def normalize_description(raw_val: Any) -> Tuple[str, str]:
    """
    Returns (cleaned_normalized_description, raw_original_description)
    """
    if raw_val is None:
        return "", ""
    raw_str = str(raw_val)
    # Collapse multiple whitespaces and tabs/newlines
    cleaned = re.sub(r"\s+", " ", raw_str).strip()
    return cleaned, raw_str


def normalize_reference(raw_val: Any) -> Optional[str]:
    """
    Normalizes reference, UTR, or check number.
    """
    if raw_val is None:
        return None
    val_str = str(raw_val).strip()
    if val_str.lower() in ["", "-", "none", "nil", "n/a", "0"]:
        return None
    # Strip trailing float artifacts (e.g., "123456.0")
    if val_str.endswith(".0"):
        val_str = val_str[:-2]
    return val_str
