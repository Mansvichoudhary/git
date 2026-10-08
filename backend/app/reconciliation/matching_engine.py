import uuid
from typing import List, Dict, Tuple, Set, Optional
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas.transaction import CanonicalTransaction
from app.schemas.reconciliation import MatchResultItem, MatchScoreDetail
from app.reconciliation.scorer import (
    calculate_match_score,
    calculate_amount_score,
    calculate_date_score,
    calculate_description_score
)


class ReconciliationMatchingEngine:

    @classmethod
    def execute_matching_pipeline(
        cls,
        run_id: str,
        bank_transactions: List[CanonicalTransaction],
        company_transactions: List[CanonicalTransaction]
    ) -> Tuple[List[MatchResultItem], List[CanonicalTransaction]]:
        """
        Executes the staged matching pipeline (Sections 4, 8, 9, 10, 11, 12):
        1. Exact Matching
        2. Strong Reference Matching
        3. Fuzzy Candidate Matching
        4. Date Tolerance Matching
        5. Composite / Partial Matching
        6. Unmatched
        Enforces strict One-to-One matching constraints.
        """
        matched_results: List[MatchResultItem] = []
        matched_company_ids: Set[str] = set()
        matched_bank_ids: Set[str] = set()

        # Build candidate lookup index by type
        comp_by_id: Dict[str, CanonicalTransaction] = {c.id: c for c in company_transactions}

        # -------------------------------------------------------------
        # Stage 1: Exact Matching (Section 8)
        # -------------------------------------------------------------
        for b in bank_transactions:
            if b.id in matched_bank_ids:
                continue

            for c in company_transactions:
                if c.id in matched_company_ids:
                    continue

                if b.type == c.type and b.amount == c.amount and b.date == c.date:
                    desc_sim = calculate_description_score(b.description, c.description)
                    ref_sim = (b.reference and c.reference and b.reference.upper() == c.reference.upper())

                    if ref_sim or desc_sim >= 0.85:
                        conf, scores, reasons, amt_diff, dt_diff = calculate_match_score(b, c)
                        m_type = "REFERENCE" if (ref_sim and desc_sim < 0.85) else "EXACT"
                        item = MatchResultItem(
                            id=f"MATCH_{uuid.uuid4().hex[:10].upper()}",
                            reconciliation_run_id=run_id,
                            bank_transaction_id=b.id,
                            company_transaction_id=c.id,
                            bank_transaction=b,
                            company_transaction=c,
                            status="MATCHED",
                            match_type=m_type,
                            confidence=max(conf, 0.95),
                            amount_difference=amt_diff,
                            date_difference_days=dt_diff,
                            scores=scores,
                            reasons=["Amount matched", "Date matched", "Direction matched"] + reasons[:2],
                            created_at=datetime.now(timezone.utc).isoformat()
                        )
                        matched_results.append(item)
                        matched_bank_ids.add(b.id)
                        matched_company_ids.add(c.id)
                        break

        # -------------------------------------------------------------
        # Stage 2: Strong Reference Matching (Section 4)
        # -------------------------------------------------------------
        for b in bank_transactions:
            if b.id in matched_bank_ids or not b.reference:
                continue

            for c in company_transactions:
                if c.id in matched_company_ids or not c.reference:
                    continue

                if b.type == c.type and b.reference.strip().upper() == c.reference.strip().upper():
                    conf, scores, reasons, amt_diff, dt_diff = calculate_match_score(b, c)
                    if amt_diff == Decimal("0.00") or conf >= 0.80:
                        status = "MATCHED" if conf >= 0.90 else "PROBABLE_MATCH"
                        item = MatchResultItem(
                            id=f"MATCH_{uuid.uuid4().hex[:10].upper()}",
                            reconciliation_run_id=run_id,
                            bank_transaction_id=b.id,
                            company_transaction_id=c.id,
                            bank_transaction=b,
                            company_transaction=c,
                            status=status,
                            match_type="REFERENCE",
                            confidence=conf,
                            amount_difference=amt_diff,
                            date_difference_days=dt_diff,
                            scores=scores,
                            reasons=["Reference / UTR matched exactly"] + reasons[:2],
                            created_at=datetime.utcnow().isoformat()
                        )
                        matched_results.append(item)
                        matched_bank_ids.add(b.id)
                        matched_company_ids.add(c.id)
                        break

        # -------------------------------------------------------------
        # Stage 3: Fuzzy Candidate Matching (Section 9)
        # -------------------------------------------------------------
        for b in bank_transactions:
            if b.id in matched_bank_ids:
                continue

            best_candidate: Optional[CanonicalTransaction] = None
            best_score = 0.0
            best_meta = None

            for c in company_transactions:
                if c.id in matched_company_ids:
                    continue

                if b.type == c.type:
                    conf, scores, reasons, amt_diff, dt_diff = calculate_match_score(b, c)
                    # Requires matching or very close amount and good description
                    if conf >= 0.75 and conf > best_score:
                        best_score = conf
                        best_candidate = c
                        best_meta = (scores, reasons, amt_diff, dt_diff)

            if best_candidate and best_score >= 0.75:
                scores, reasons, amt_diff, dt_diff = best_meta
                # Hard rule (Section 7 & 9): if date or amount differs, classify as PROBABLE_MATCH
                status = "MATCHED" if (best_score >= 0.90 and dt_diff == 0 and amt_diff == Decimal("0.00")) else "PROBABLE_MATCH"
                m_type = "DATE_TOLERANCE" if dt_diff > 0 else "FUZZY"
                item = MatchResultItem(
                    id=f"MATCH_{uuid.uuid4().hex[:10].upper()}",
                    reconciliation_run_id=run_id,
                    bank_transaction_id=b.id,
                    company_transaction_id=best_candidate.id,
                    bank_transaction=b,
                    company_transaction=best_candidate,
                    status=status,
                    match_type=m_type,
                    confidence=best_score,
                    amount_difference=amt_diff,
                    date_difference_days=dt_diff,
                    scores=scores,
                    reasons=reasons,
                    created_at=datetime.now(timezone.utc).isoformat()
                )
                matched_results.append(item)
                matched_bank_ids.add(b.id)
                matched_company_ids.add(best_candidate.id)

        # -------------------------------------------------------------
        # Stage 4: Date Tolerance Matching (Section 9 & 17)
        # -------------------------------------------------------------
        for b in bank_transactions:
            if b.id in matched_bank_ids:
                continue

            for c in company_transactions:
                if c.id in matched_company_ids:
                    continue

                if b.type == c.type and b.amount == c.amount:
                    dt_diff = abs((b.date - c.date).days)
                    if 1 <= dt_diff <= 5:
                        conf, scores, reasons, amt_diff, _ = calculate_match_score(b, c)
                        if conf >= 0.70:
                            item = MatchResultItem(
                                id=f"MATCH_{uuid.uuid4().hex[:10].upper()}",
                                reconciliation_run_id=run_id,
                                bank_transaction_id=b.id,
                                company_transaction_id=c.id,
                                bank_transaction=b,
                                company_transaction=c,
                                status="PROBABLE_MATCH",
                                match_type="DATE_TOLERANCE",
                                confidence=conf,
                                amount_difference=amt_diff,
                                date_difference_days=dt_diff,
                                scores=scores,
                                reasons=[f"Amount matches; date differs by {dt_diff} days (timing window)"] + reasons[:2],
                                created_at=datetime.now(timezone.utc).isoformat()
                            )
                            matched_results.append(item)
                            matched_bank_ids.add(b.id)
                            matched_company_ids.add(c.id)
                            break

        # -------------------------------------------------------------
        # Stage 5: Composite / Partial Matching (Section 12)
        # -------------------------------------------------------------
        for b in bank_transactions:
            if b.id in matched_bank_ids:
                continue

            # Look for 2 available company transactions that sum to b.amount
            available_comp = [c for c in company_transactions if c.id not in matched_company_ids and c.type == b.type]
            composite_found = False

            for i in range(len(available_comp)):
                for j in range(i + 1, len(available_comp)):
                    c1, c2 = available_comp[i], available_comp[j]
                    if (c1.amount + c2.amount) == b.amount:
                        # Check date proximity
                        d_diff = max(abs((b.date - c1.date).days), abs((b.date - c2.date).days))
                        if d_diff <= 5:
                            item = MatchResultItem(
                                id=f"MATCH_{uuid.uuid4().hex[:10].upper()}",
                                reconciliation_run_id=run_id,
                                bank_transaction_id=b.id,
                                company_transaction_id=f"{c1.id}+{c2.id}",
                                bank_transaction=b,
                                company_transaction=c1,  # anchor representation
                                status="PROBABLE_MATCH",
                                match_type="COMPOSITE",
                                confidence=0.88,
                                amount_difference=Decimal("0.00"),
                                date_difference_days=d_diff,
                                scores=MatchScoreDetail(amount_score=1.0, date_score=0.8, type_score=1.0, total_confidence=0.88),
                                reasons=[
                                    f"Composite Match: Bank ₹{b.amount:,.2f} equals Company ₹{c1.amount:,.2f} + ₹{c2.amount:,.2f}",
                                    f"Matched across 2 split company accounting records"
                                ],
                                created_at=datetime.now(timezone.utc).isoformat()
                            )
                            matched_results.append(item)
                            matched_bank_ids.add(b.id)
                            matched_company_ids.add(c1.id)
                            matched_company_ids.add(c2.id)
                            composite_found = True
                            break
                if composite_found:
                    break

        # -------------------------------------------------------------
        # Stage 6: Unmatched Bank Transactions (Section 10)
        # -------------------------------------------------------------
        for b in bank_transactions:
            if b.id not in matched_bank_ids:
                item = MatchResultItem(
                    id=f"MATCH_{uuid.uuid4().hex[:10].upper()}",
                    reconciliation_run_id=run_id,
                    bank_transaction_id=b.id,
                    company_transaction_id=None,
                    bank_transaction=b,
                    company_transaction=None,
                    status="UNMATCHED",
                    match_type="NONE",
                    confidence=0.0,
                    amount_difference=b.amount,
                    date_difference_days=0,
                    scores=MatchScoreDetail(),
                    reasons=["No corresponding candidate transaction found in company accounts"],
                    created_at=datetime.now(timezone.utc).isoformat()
                )
                matched_results.append(item)

        # Unmatched company transactions
        unmatched_company_txns = [c for c in company_transactions if c.id not in matched_company_ids]

        return matched_results, unmatched_company_txns
