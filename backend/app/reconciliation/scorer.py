from datetime import date
from decimal import Decimal
from typing import Tuple, List
from rapidfuzz import fuzz
from app.schemas.transaction import CanonicalTransaction
from app.schemas.reconciliation import MatchScoreDetail


def calculate_amount_score(bank_amt: Decimal, comp_amt: Decimal) -> Tuple[float, Decimal]:
    """
    Computes amount similarity score (40% weight) and absolute difference.
    Exact match: 1.0. Minor pennies difference (<=1%): 0.90.
    """
    diff = abs(bank_amt - comp_amt)
    if diff == Decimal("0.00"):
        return 1.0, diff

    max_amt = max(bank_amt, comp_amt)
    if max_amt == Decimal("0.00"):
        return 1.0, diff

    pct_diff = float(diff / max_amt)
    if pct_diff <= 0.005:  # <= 0.5% difference
        return 0.95, diff
    elif pct_diff <= 0.02:  # <= 2% difference
        return 0.85, diff
    elif pct_diff <= 0.05:  # <= 5% difference
        return 0.60, diff
    elif pct_diff <= 0.10:  # <= 10% difference
        return 0.30, diff
    else:
        return 0.0, diff


def calculate_date_score(bank_dt: date, comp_dt: date) -> Tuple[float, int]:
    """
    Computes date similarity score (20% weight) and absolute day difference.
    0 days = 1.0, 1 day = 0.9, 2 days = 0.8, 3 days = 0.6, 4-5 days = 0.4.
    """
    days = abs((bank_dt - comp_dt).days)
    if days == 0:
        return 1.0, 0
    elif days == 1:
        return 0.90, 1
    elif days == 2:
        return 0.80, 2
    elif days == 3:
        return 0.60, 3
    elif days <= 5:
        return 0.40, days
    else:
        return 0.0, days


def calculate_description_score(desc_a: str, desc_b: str) -> float:
    """
    Computes normalized description similarity (20% weight) via RapidFuzz token set ratio.
    """
    clean_a = desc_a.strip().lower()
    clean_b = desc_b.strip().lower()
    if clean_a == clean_b:
        return 1.0
    
    sim = max(
        fuzz.token_set_ratio(clean_a, clean_b),
        fuzz.token_sort_ratio(clean_a, clean_b)
    ) / 100.0
    return round(sim, 2)


def calculate_reference_score(ref_a: str | None, ref_b: str | None) -> float:
    """
    Computes reference similarity score (15% weight).
    """
    if not ref_a or not ref_b:
        return 0.0
    
    clean_a = ref_a.strip().upper()
    clean_b = ref_b.strip().upper()
    if clean_a == clean_b:
        return 1.0
    if clean_a in clean_b or clean_b in clean_a:
        return 0.85
    return 0.0


def calculate_match_score(
    bank_txn: CanonicalTransaction,
    comp_txn: CanonicalTransaction
) -> Tuple[float, MatchScoreDetail, List[str], Decimal, int]:
    """
    Comprehensive multi-factor deterministic scoring (Sections 5 & 6).
    Formula:
        match_score = amount_score * 0.40
                    + date_score   * 0.20
                    + desc_score   * 0.20
                    + ref_score    * 0.15
                    + type_score   * 0.05
    """
    reasons: List[str] = []

    # 1. Type check
    if bank_txn.type != comp_txn.type:
        type_score = 0.0
        reasons.append(f"Direction conflict: Bank is {bank_txn.type} but Company is {comp_txn.type}")
        # Hard constraint: conflicting direction prevents matching
        scores = MatchScoreDetail(
            amount_score=0.0, date_score=0.0, description_score=0.0,
            reference_score=0.0, type_score=0.0, total_confidence=0.0
        )
        return 0.0, scores, reasons, abs(bank_txn.amount - comp_txn.amount), abs((bank_txn.date - comp_txn.date).days)
    else:
        type_score = 1.0

    # 2. Amount score
    amt_score, amt_diff = calculate_amount_score(bank_txn.amount, comp_txn.amount)
    if amt_diff == Decimal("0.00"):
        reasons.append("Amount matched exactly")
    elif amt_score > 0:
        reasons.append(f"Amount difference of ₹{amt_diff:.2f}")
    else:
        reasons.append(f"Significant amount mismatch: ₹{bank_txn.amount} vs ₹{comp_txn.amount}")

    # 3. Date score
    dt_score, dt_diff = calculate_date_score(bank_txn.date, comp_txn.date)
    if dt_diff == 0:
        reasons.append("Date matched exactly")
    elif dt_diff <= 2:
        reasons.append(f"Date differs by {dt_diff} day{'s' if dt_diff > 1 else ''} (within tolerance)")
    else:
        reasons.append(f"Date differs by {dt_diff} days")

    # 4. Description score
    desc_score = calculate_description_score(bank_txn.description, comp_txn.description)
    if desc_score >= 0.90:
        reasons.append("Description strongly matched")
    elif desc_score >= 0.70:
        reasons.append(f"Description partially matched ({int(desc_score * 100)}%)")

    # 5. Reference score
    ref_score = calculate_reference_score(bank_txn.reference, comp_txn.reference)
    if ref_score == 1.0:
        reasons.append("Reference / UTR number matched exactly")

    # Weighted calculation
    if not bank_txn.reference and not comp_txn.reference:
        # Reference absent on both sides - normalize over amount, date, description, type (0.85 base)
        raw_score = (
            amt_score * 0.40 +
            dt_score * 0.20 +
            desc_score * 0.20 +
            type_score * 0.05
        )
        total_score = raw_score / 0.85
    else:
        total_score = (
            amt_score * 0.40 +
            dt_score * 0.20 +
            desc_score * 0.20 +
            ref_score * 0.15 +
            type_score * 0.05
        )

    # Hard constraints: if amount doesn't match and description is low, cap total score
    if amt_score == 0.0:
        total_score = min(total_score, 0.45)

    total_score = min(round(total_score, 4), 1.0)

    scores = MatchScoreDetail(
        amount_score=round(amt_score, 2),
        date_score=round(dt_score, 2),
        description_score=round(desc_score, 2),
        reference_score=round(ref_score, 2),
        type_score=round(type_score, 2),
        total_confidence=round(total_score, 2)
    )

    return total_score, scores, reasons, amt_diff, dt_diff
