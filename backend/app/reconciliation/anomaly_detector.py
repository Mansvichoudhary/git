import uuid
from typing import List, Dict
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas.transaction import CanonicalTransaction
from app.schemas.reconciliation import MatchResultItem, AnomalyItem
from app.reconciliation.scorer import calculate_description_score


class ReconciliationAnomalyDetector:

    @classmethod
    def detect_anomalies(
        cls,
        run_id: str,
        matches: List[MatchResultItem],
        bank_transactions: List[CanonicalTransaction],
        company_transactions: List[CanonicalTransaction],
        unmatched_company_txns: List[CanonicalTransaction]
    ) -> List[AnomalyItem]:
        """
        Detects anomalies according to Sections 13 - 17:
        - DUPLICATE_TRANSACTION (Bank-Bank and Company-Company)
        - MISSING_IN_COMPANY (Unmatched bank transactions)
        - MISSING_IN_BANK (Unmatched company transactions)
        - DATE_MISMATCH
        - AMOUNT_MISMATCH
        - COMPOSITE_MATCH
        """
        anomalies: List[AnomalyItem] = []

        # -------------------------------------------------------------
        # 1. Duplicate Detection within Bank Statement (Section 13)
        # -------------------------------------------------------------
        for i in range(len(bank_transactions)):
            for j in range(i + 1, len(bank_transactions)):
                b1 = bank_transactions[i]
                b2 = bank_transactions[j]
                if b1.amount == b2.amount and b1.type == b2.type:
                    days_apart = abs((b1.date - b2.date).days)
                    desc_sim = calculate_description_score(b1.description, b2.description)
                    if days_apart <= 1 and desc_sim >= 0.80:
                        anomalies.append(AnomalyItem(
                            id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                            reconciliation_run_id=run_id,
                            transaction_id=b1.id,
                            candidate_transaction_id=b2.id,
                            transaction=b1,
                            candidate_transaction=b2,
                            type="DUPLICATE_TRANSACTION",
                            severity="HIGH",
                            status="PENDING",
                            amount_difference=Decimal("0.00"),
                            date_difference_days=days_apart,
                            evidence=[
                                f"Identical amount of ₹{b1.amount:,.2f} appears twice in Bank Statement",
                                f"Dates are {b1.date} and {b2.date} ({days_apart} days apart)",
                                f"Description similarity: {int(desc_sim * 100)}%",
                                f"Possible double billing or duplicate payment"
                            ],
                            created_at=datetime.now(timezone.utc).isoformat()
                        ))

        # -------------------------------------------------------------
        # 2. Duplicate Detection within Company Accounts (Section 13)
        # -------------------------------------------------------------
        for i in range(len(company_transactions)):
            for j in range(i + 1, len(company_transactions)):
                c1 = company_transactions[i]
                c2 = company_transactions[j]
                if c1.amount == c2.amount and c1.type == c2.type:
                    days_apart = abs((c1.date - c2.date).days)
                    desc_sim = calculate_description_score(c1.description, c2.description)
                    if days_apart <= 1 and desc_sim >= 0.85:
                        anomalies.append(AnomalyItem(
                            id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                            reconciliation_run_id=run_id,
                            transaction_id=c1.id,
                            candidate_transaction_id=c2.id,
                            transaction=c1,
                            candidate_transaction=c2,
                            type="DUPLICATE_TRANSACTION",
                            severity="MEDIUM",
                            status="PENDING",
                            amount_difference=Decimal("0.00"),
                            date_difference_days=days_apart,
                            evidence=[
                                f"Identical entry of ₹{c1.amount:,.2f} recorded twice in Company Accounts",
                                f"Dates: {c1.date} and {c2.date}",
                                f"Possible double ledger journal posting"
                            ],
                            created_at=datetime.now(timezone.utc).isoformat()
                        ))

        # -------------------------------------------------------------
        # 3. Matches Anomalies (Date Mismatch, Amount Mismatch, Composite)
        # -------------------------------------------------------------
        for m in matches:
            if m.status == "PROBABLE_MATCH":
                if m.match_type == "COMPOSITE":
                    anomalies.append(AnomalyItem(
                        id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                        reconciliation_run_id=run_id,
                        transaction_id=m.bank_transaction_id,
                        candidate_transaction_id=m.company_transaction_id,
                        transaction=m.bank_transaction,
                        candidate_transaction=m.company_transaction,
                        type="COMPOSITE_MATCH",
                        severity="LOW",
                        status="PENDING",
                        amount_difference=Decimal("0.00"),
                        date_difference_days=m.date_difference_days,
                        evidence=m.reasons,
                        created_at=datetime.now(timezone.utc).isoformat()
                    ))
                elif m.amount_difference > Decimal("0.00"):
                    anomalies.append(AnomalyItem(
                        id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                        reconciliation_run_id=run_id,
                        transaction_id=m.bank_transaction_id,
                        candidate_transaction_id=m.company_transaction_id,
                        transaction=m.bank_transaction,
                        candidate_transaction=m.company_transaction,
                        type="AMOUNT_MISMATCH",
                        severity="HIGH" if m.amount_difference > Decimal("500.00") else "MEDIUM",
                        status="PENDING",
                        amount_difference=m.amount_difference,
                        date_difference_days=m.date_difference_days,
                        evidence=[
                            f"Bank amount is ₹{m.bank_transaction.amount:,.2f} but Company record is ₹{m.company_transaction.amount:,.2f}",
                            f"Deterministic discrepancy of ₹{m.amount_difference:,.2f}",
                            f"Description match: {int(m.scores.description_score * 100)}%"
                        ],
                        created_at=datetime.now(timezone.utc).isoformat()
                    ))
                elif m.date_difference_days > 0:
                    anomalies.append(AnomalyItem(
                        id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                        reconciliation_run_id=run_id,
                        transaction_id=m.bank_transaction_id,
                        candidate_transaction_id=m.company_transaction_id,
                        transaction=m.bank_transaction,
                        candidate_transaction=m.company_transaction,
                        type="DATE_MISMATCH",
                        severity="LOW" if m.date_difference_days <= 2 else "MEDIUM",
                        status="PENDING",
                        amount_difference=Decimal("0.00"),
                        date_difference_days=m.date_difference_days,
                        evidence=[
                            f"Amount matches exactly (₹{m.bank_transaction.amount:,.2f})",
                            f"Bank date is {m.bank_transaction.date} vs Company date {m.company_transaction.date}",
                            f"Timing gap of {m.date_difference_days} day(s) (likely clearing/settlement delay)"
                        ],
                        created_at=datetime.now(timezone.utc).isoformat()
                    ))

        # -------------------------------------------------------------
        # 4. Unmatched Bank Transactions -> MISSING_IN_COMPANY (Section 15)
        # -------------------------------------------------------------
        for m in matches:
            if m.status == "UNMATCHED" and m.bank_transaction:
                anomalies.append(AnomalyItem(
                    id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                    reconciliation_run_id=run_id,
                    transaction_id=m.bank_transaction_id,
                    candidate_transaction_id=None,
                    transaction=m.bank_transaction,
                    candidate_transaction=None,
                    type="MISSING_IN_COMPANY",
                    severity="HIGH" if m.bank_transaction.amount >= Decimal("10000.00") else "MEDIUM",
                    status="PENDING",
                    amount_difference=m.bank_transaction.amount,
                    date_difference_days=0,
                    evidence=[
                        f"Bank record ₹{m.bank_transaction.amount:,.2f} ({m.bank_transaction.description}) has no ledger match",
                        f"Transaction date: {m.bank_transaction.date}",
                        f"Requires investigation: possible unrecorded bank charge, fee, or missing entry"
                    ],
                    created_at=datetime.now(timezone.utc).isoformat()
                ))

        # -------------------------------------------------------------
        # 5. Unmatched Company Transactions -> MISSING_IN_BANK (Section 15)
        # -------------------------------------------------------------
        for c in unmatched_company_txns:
            anomalies.append(AnomalyItem(
                id=f"ANOM_{uuid.uuid4().hex[:10].upper()}",
                reconciliation_run_id=run_id,
                transaction_id=c.id,
                candidate_transaction_id=None,
                transaction=c,
                candidate_transaction=None,
                type="MISSING_IN_BANK",
                severity="HIGH" if c.amount >= Decimal("10000.00") else "MEDIUM",
                status="PENDING",
                amount_difference=c.amount,
                date_difference_days=0,
                evidence=[
                    f"Company ledger shows ₹{c.amount:,.2f} ({c.description}) with no bank statement record",
                    f"Entry date: {c.date}",
                    f"Possible unpresented cheque, delayed deposit, or omitted entry"
                ],
                created_at=datetime.now(timezone.utc).isoformat()
            ))

        return anomalies
