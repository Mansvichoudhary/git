import json
import uuid
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from decimal import Decimal

from app.core.database import get_db_connection
from app.schemas.transaction import CanonicalTransaction
from app.schemas.reconciliation import (
    MatchResultItem,
    AnomalyItem,
    AIInvestigationResult,
    HumanReviewSubmission,
    ReconciliationRunResponse,
    ReconciliationSummaryReport,
    MatchScoreDetail
)
from app.reconciliation.matching_engine import ReconciliationMatchingEngine
from app.reconciliation.anomaly_detector import ReconciliationAnomalyDetector
from app.reconciliation.ai_investigator import AIInvestigationAgent


class ReconciliationService:

    @classmethod
    def start_reconciliation(
        cls,
        reconciliation_id: str,
        bank_source_id: Optional[str] = None,
        company_source_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes complete Process 02:
        1. Loads canonical transactions for Bank and Company Accounts
        2. Executes staged matching pipeline
        3. Detects financial anomalies
        4. Triggers AI forensic investigations on exceptions
        5. Persists matches, anomalies, and investigations
        """
        conn = get_db_connection()

        # 1. Load canonical transactions from database
        query_bank = """
            SELECT * FROM transactions 
            WHERE reconciliation_id = ? AND (source_type = 'BANK_STATEMENT' OR source_type = 'BANK')
            ORDER BY date ASC
        """
        bank_rows = conn.execute(query_bank, (reconciliation_id,)).fetchall()

        query_comp = """
            SELECT * FROM transactions 
            WHERE reconciliation_id = ? AND (source_type = 'ACCOUNTING_LEDGER' OR source_type = 'COMPANY_ACCOUNTS' OR source_type = 'LEDGER')
            ORDER BY date ASC
        """
        comp_rows = conn.execute(query_comp, (reconciliation_id,)).fetchall()

        # If empty, look for any transactions associated with this reconciliation
        if not comp_rows and bank_rows:
            all_txns = conn.execute("SELECT * FROM transactions WHERE reconciliation_id = ?", (reconciliation_id,)).fetchall()
            # Split transactions between sources if present
            sources = conn.execute("SELECT id, source_type FROM sources WHERE reconciliation_id = ?", (reconciliation_id,)).fetchall()
            if len(sources) >= 2:
                s_bank = sources[0]["id"]
                s_comp = sources[1]["id"]
                bank_rows = [t for t in all_txns if t["source_id"] == s_bank]
                comp_rows = [t for t in all_txns if t["source_id"] == s_comp]

        bank_txns: List[CanonicalTransaction] = [cls._row_to_canonical(r) for r in bank_rows]
        comp_txns: List[CanonicalTransaction] = [cls._row_to_canonical(r) for r in comp_rows]

        run_id = f"RECON_{uuid.uuid4().hex[:10].upper()}"

        with conn:
            conn.execute(
                """
                INSERT INTO reconciliation_runs (id, reconciliation_id, bank_source_id, company_source_id, status, started_at)
                VALUES (?, ?, ?, ?, 'MATCHING', CURRENT_TIMESTAMP)
                """,
                (run_id, reconciliation_id, bank_source_id, company_source_id)
            )

        # 2. Run Staged Deterministic Matching Engine
        matches, unmatched_comp = ReconciliationMatchingEngine.execute_matching_pipeline(
            run_id=run_id,
            bank_transactions=bank_txns,
            company_transactions=comp_txns
        )

        # 3. Run Anomaly Detection
        anomalies = ReconciliationAnomalyDetector.detect_anomalies(
            run_id=run_id,
            matches=matches,
            bank_transactions=bank_txns,
            company_transactions=comp_txns,
            unmatched_company_txns=unmatched_comp
        )

        # 4. Trigger AI Forensic Investigations
        investigations: List[AIInvestigationResult] = []
        for anom in anomalies:
            inv = AIInvestigationAgent.investigate_anomaly(anom)
            investigations.append(inv)

        # 5. Persist Everything to Database
        with conn:
            # Matches
            for m in matches:
                conn.execute(
                    """
                    INSERT INTO matches (
                        id, reconciliation_run_id, bank_transaction_id, company_transaction_id,
                        status, match_type, confidence, amount_difference, date_difference_days,
                        amount_score, date_score, description_score, reference_score, type_score,
                        reasons
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        m.id, run_id, m.bank_transaction_id, m.company_transaction_id,
                        m.status, m.match_type, float(m.confidence), float(m.amount_difference),
                        m.date_difference_days, m.scores.amount_score, m.scores.date_score,
                        m.scores.description_score, m.scores.reference_score, m.scores.type_score,
                        json.dumps(m.reasons)
                    )
                )

            # Anomalies
            for a in anomalies:
                conn.execute(
                    """
                    INSERT INTO anomalies (
                        id, reconciliation_run_id, transaction_id, candidate_transaction_id,
                        type, severity, status, amount_difference, date_difference_days, evidence
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        a.id, run_id, a.transaction_id, a.candidate_transaction_id,
                        a.type, a.severity, a.status, float(a.amount_difference),
                        a.date_difference_days, json.dumps(a.evidence)
                    )
                )

            # Investigations
            for inv in investigations:
                conn.execute(
                    """
                    INSERT INTO investigations (
                        id, anomaly_id, finding, conclusion, confidence, risk, evidence, recommended_action, ai_model
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inv.id, inv.anomaly_id, inv.finding, inv.conclusion, float(inv.confidence),
                        inv.risk, json.dumps(inv.evidence), inv.recommended_action, inv.ai_model
                    )
                )

            # Update reconciliation run status
            run_status = "REVIEW_REQUIRED" if anomalies or any(m.status != "MATCHED" for m in matches) else "COMPLETED"
            conn.execute(
                """
                UPDATE reconciliation_runs 
                SET status = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (run_status, run_id)
            )

        conn.close()

        return {
            "run_id": run_id,
            "reconciliation_id": reconciliation_id,
            "status": run_status,
            "total_bank_transactions": len(bank_txns),
            "total_company_transactions": len(comp_txns),
            "matched_count": sum(1 for m in matches if m.status == "MATCHED"),
            "probable_match_count": sum(1 for m in matches if m.status == "PROBABLE_MATCH"),
            "unmatched_count": sum(1 for m in matches if m.status == "UNMATCHED"),
            "anomalies_count": len(anomalies)
        }

    @staticmethod
    def get_reconciliation_summary(reconciliation_id: str) -> ReconciliationSummaryReport:
        conn = get_db_connection()
        # Get latest run
        run_row = conn.execute(
            """
            SELECT * FROM reconciliation_runs 
            WHERE reconciliation_id = ? 
            ORDER BY created_at DESC LIMIT 1
            """,
            (reconciliation_id,)
        ).fetchone()

        if not run_row:
            # Create a default completed response
            return ReconciliationSummaryReport(
                run_id="NONE",
                reconciliation_id=reconciliation_id,
                status="REVIEW REQUIRED",
                total_bank_transactions=0,
                total_company_transactions=0,
                matched_count=0,
                probable_match_count=0,
                unmatched_count=0,
                anomalies_count=0,
                duplicate_count=0,
                total_amount_difference=Decimal("0.00"),
                generated_at=datetime.now(timezone.utc).isoformat()
            )

        run_id = run_row["id"]
        matches_rows = conn.execute("SELECT * FROM matches WHERE reconciliation_run_id = ?", (run_id,)).fetchall()
        anomalies_rows = conn.execute("SELECT * FROM anomalies WHERE reconciliation_run_id = ?", (run_id,)).fetchall()

        conn.close()

        matches: List[MatchResultItem] = []
        for r in matches_rows:
            d = dict(r)
            matches.append(MatchResultItem(
                id=d["id"],
                reconciliation_run_id=d["reconciliation_run_id"],
                bank_transaction_id=d["bank_transaction_id"],
                company_transaction_id=d["company_transaction_id"],
                status=d["status"],
                match_type=d["match_type"],
                confidence=d["confidence"],
                amount_difference=Decimal(str(d["amount_difference"] or 0)),
                date_difference_days=d["date_difference_days"] or 0,
                scores=MatchScoreDetail(
                    amount_score=d.get("amount_score", 0),
                    date_score=d.get("date_score", 0),
                    description_score=d.get("description_score", 0),
                    reference_score=d.get("reference_score", 0),
                    type_score=d.get("type_score", 0),
                    total_confidence=d.get("confidence", 0)
                ),
                reasons=json.loads(d["reasons"]) if d["reasons"] else [],
                created_at=d["created_at"]
            ))

        anomalies: List[AnomalyItem] = []
        duplicate_count = 0
        total_diff = Decimal("0.00")

        for r in anomalies_rows:
            d = dict(r)
            if d["type"] == "DUPLICATE_TRANSACTION":
                duplicate_count += 1
            diff = Decimal(str(d["amount_difference"] or 0))
            total_diff += diff
            anomalies.append(AnomalyItem(
                id=d["id"],
                reconciliation_run_id=d["reconciliation_run_id"],
                transaction_id=d["transaction_id"],
                candidate_transaction_id=d["candidate_transaction_id"],
                type=d["type"],
                severity=d["severity"],
                status=d["status"],
                amount_difference=diff,
                date_difference_days=d["date_difference_days"] or 0,
                evidence=json.loads(d["evidence"]) if d["evidence"] else [],
                created_at=d["created_at"]
            ))

        matched_count = sum(1 for m in matches if m.status == "MATCHED")
        probable_count = sum(1 for m in matches if m.status == "PROBABLE_MATCH")
        unmatched_count = sum(1 for m in matches if m.status == "UNMATCHED")

        overall_status = "RECONCILIATION COMPLETE" if len(anomalies) == 0 and probable_count == 0 else "REVIEW REQUIRED"

        return ReconciliationSummaryReport(
            run_id=run_id,
            reconciliation_id=reconciliation_id,
            status=overall_status,
            total_bank_transactions=matched_count + probable_count + unmatched_count,
            total_company_transactions=matched_count + probable_count,
            matched_count=matched_count,
            probable_match_count=probable_count,
            unmatched_count=unmatched_count,
            anomalies_count=len(anomalies),
            duplicate_count=duplicate_count,
            total_amount_difference=total_diff,
            matches=matches,
            anomalies=anomalies,
            generated_at=datetime.now(timezone.utc).isoformat()
        )

    @staticmethod
    def get_matches(reconciliation_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        query = """
            SELECT m.*, b.description as bank_desc, b.amount as bank_amount, b.date as bank_date,
                        c.description as comp_desc, c.amount as comp_amount, c.date as comp_date
            FROM matches m
            JOIN reconciliation_runs r ON m.reconciliation_run_id = r.id
            LEFT JOIN transactions b ON m.bank_transaction_id = b.id
            LEFT JOIN transactions c ON m.company_transaction_id = c.id
            WHERE r.reconciliation_id = ?
        """
        params = [reconciliation_id]
        if status_filter:
            query += " AND m.status = ?"
            params.append(status_filter)
        query += " ORDER BY m.confidence DESC"

        rows = conn.execute(query, params).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("reasons"):
                try:
                    d["reasons"] = json.loads(d["reasons"])
                except Exception:
                    pass
            results.append(d)
        return results

    @staticmethod
    def get_anomalies(reconciliation_id: str, severity_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        query = """
            SELECT a.*, i.finding, i.conclusion, i.risk, i.confidence as ai_confidence, i.recommended_action,
                        t.description as txn_desc, t.amount as txn_amount, t.date as txn_date
            FROM anomalies a
            JOIN reconciliation_runs r ON a.reconciliation_run_id = r.id
            LEFT JOIN investigations i ON a.id = i.anomaly_id
            LEFT JOIN transactions t ON a.transaction_id = t.id
            WHERE r.reconciliation_id = ?
        """
        params = [reconciliation_id]
        if severity_filter:
            query += " AND a.severity = ?"
            params.append(severity_filter)
        query += " ORDER BY a.created_at ASC"

        rows = conn.execute(query, params).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("evidence"):
                try:
                    d["evidence"] = json.loads(d["evidence"])
                except Exception:
                    pass
            results.append(d)
        return results

    @staticmethod
    def review_anomaly(anomaly_id: str, review: HumanReviewSubmission) -> Dict[str, Any]:
        """
        Human Review audit action (Section 29).
        User confirms match, marks unmatched, or flags duplicate.
        """
        conn = get_db_connection()
        review_id = f"REV_{uuid.uuid4().hex[:10].upper()}"

        new_status = "CONFIRMED" if review.action == "CONFIRM_MATCH" else "RESOLVED"

        with conn:
            # 1. Insert audit review
            conn.execute(
                """
                INSERT INTO human_reviews (id, anomaly_id, user_id, action, comment)
                VALUES (?, ?, ?, ?, ?)
                """,
                (review_id, anomaly_id, review.user_id, review.action, review.comment)
            )

            # 2. Update anomaly status
            conn.execute(
                "UPDATE anomalies SET status = ? WHERE id = ?",
                (new_status, anomaly_id)
            )

            # 3. If confirming match, update corresponding matches record
            if review.action == "CONFIRM_MATCH":
                anom = conn.execute("SELECT * FROM anomalies WHERE id = ?", (anomaly_id,)).fetchone()
                if anom and anom["candidate_transaction_id"]:
                    conn.execute(
                        """
                        UPDATE matches 
                        SET status = 'MATCHED', confidence = 1.0 
                        WHERE bank_transaction_id = ? AND company_transaction_id = ?
                        """,
                        (anom["transaction_id"], anom["candidate_transaction_id"])
                    )

        conn.close()
        return {
            "review_id": review_id,
            "anomaly_id": anomaly_id,
            "action": review.action,
            "status": new_status,
            "message": f"Human review action '{review.action}' recorded successfully."
        }

    @staticmethod
    def _row_to_canonical(row: Any) -> CanonicalTransaction:
        d = dict(row)
        clean_id = d["id"].split("_", 2)[-1] if d["id"].count("_") >= 2 else d["id"]
        prov = d.get("provenance")
        if prov and isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except Exception:
                prov = {}
        elif not prov:
            prov = {}

        return CanonicalTransaction(
            id=d["id"],
            reconciliation_id=d.get("reconciliation_id", "REC_DEMO_01"),
            source_id=d.get("source_id", "SRC_DEMO_BANK"),
            source_type=d.get("source_type", "BANK_STATEMENT"),
            date=datetime.strptime(d["date"], "%Y-%m-%d").date(),
            description=d["description"],
            description_original=d.get("description_original", d["description"]),
            amount=Decimal(str(d["amount"])),
            type=d["type"],
            reference=d.get("reference"),
            balance=Decimal(str(d["balance"])) if d.get("balance") is not None else None,
            currency=d.get("currency", "INR"),
            account_id=d.get("account_id"),
            provenance=prov,
            source_row=d.get("source_row")
        )

    @classmethod
    def get_input_status(cls, reconciliation_id: str) -> Dict[str, Any]:
        """
        Returns ready status and record count for Bank Statement vs Company Ledger.
        """
        conn = get_db_connection()
        b_count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE reconciliation_id = ? AND (source_type = 'BANK_STATEMENT' OR source_type = 'BANK')",
            (reconciliation_id,)
        ).fetchone()[0]
        c_count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE reconciliation_id = ? AND (source_type = 'ACCOUNTING_LEDGER' OR source_type = 'COMPANY_ACCOUNTS' OR source_type = 'LEDGER')",
            (reconciliation_id,)
        ).fetchone()[0]
        conn.close()
        return {
            "reconciliation_id": reconciliation_id,
            "bank_count": b_count,
            "company_count": c_count,
            "bank_ready": b_count > 0,
            "company_ready": c_count > 0,
            "can_start": b_count > 0 and c_count > 0
        }

    @classmethod
    def seed_demo_transactions(cls, reconciliation_id: str = "REC_DEMO_01") -> Dict[str, Any]:
        """
        Seeds standard representative Bank Statement and Accounting Ledger transactions
        for testing all reconciliation stages and anomaly types.
        """
        conn = get_db_connection()
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO companies (id, company_name, base_currency) VALUES ('COMP_DEMO_01', 'Acme FinTech Corp', 'INR')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO reconciliations (id, company_id, name) VALUES (?, 'COMP_DEMO_01', 'October 2026 Monthly Recon')",
                (reconciliation_id,)
            )
            conn.execute(
                "INSERT OR IGNORE INTO parse_jobs (id, file_id, status) VALUES ('JOB_DEMO_01', 'FILE_DEMO_01', 'COMPLETED')"
            )

            conn.execute("DELETE FROM transactions WHERE reconciliation_id = ?", (reconciliation_id,))
            conn.execute("DELETE FROM matches WHERE reconciliation_run_id IN (SELECT id FROM reconciliation_runs WHERE reconciliation_id = ?)", (reconciliation_id,))
            conn.execute("DELETE FROM anomalies WHERE reconciliation_run_id IN (SELECT id FROM reconciliation_runs WHERE reconciliation_id = ?)", (reconciliation_id,))
            conn.execute("DELETE FROM reconciliation_runs WHERE reconciliation_id = ?", (reconciliation_id,))

            bank_data = [
                ("TXN_BANK_01", "2026-10-01", "UPI-AMAZON PAY INDIA-429182@okhdfc", 1250.00, "DEBIT", "UPI0092817", 98750.00, 1),
                ("TXN_BANK_02", "2026-10-02", "SALARY CREDIT OCT 2026 ACME CORP", 85000.00, "CREDIT", "SAL992810", 183750.00, 2),
                ("TXN_BANK_03", "2026-10-04", "NEFT-ABC LOGISTICS CORP-SERVICES", 48500.00, "DEBIT", "NEFT881920", 135250.00, 3),
                ("TXN_BANK_04", "2026-10-05", "ATM CASH WITHDRAWAL BKC BRANCH", 10000.00, "DEBIT", "ATM109281", 125250.00, 4),
                ("TXN_BANK_05", "2026-10-06", "AMAZON WEB SERVICES CLOUD HOSTING", 25000.00, "DEBIT", "AWS771920", 100250.00, 5),
                ("TXN_BANK_06", "2026-10-06", "AMAZON WEB SERVICES CLOUD HOSTING", 25000.00, "DEBIT", "AWS771920", 75250.00, 6),
                ("TXN_BANK_07", "2026-10-07", "OFFICE SUPPLIES INDIA PVT LTD", 4200.00, "DEBIT", "OFF99120", 71050.00, 7),
                ("TXN_BANK_08", "2026-10-08", "BULK VENDOR PAYMENT VEND-992", 25000.00, "DEBIT", "UTR9928", 46050.00, 8),
            ]

            for bid, bdate, bdesc, bamt, btype, bref, bbal, brow in bank_data:
                prov = json.dumps({"file_id": "FILE_BANK_HDFC_01", "filename": "HDFC_October_Statement.pdf", "page": 1, "row": brow})
                conn.execute(
                    """
                    INSERT INTO transactions (
                        id, reconciliation_id, source_id, source_type, parse_job_id,
                        date, description, description_original, amount, type, reference, balance,
                        currency, provenance, source_row
                    ) VALUES (?, ?, 'SRC_DEMO_BANK', 'BANK_STATEMENT', 'JOB_DEMO_01', ?, ?, ?, ?, ?, ?, ?, 'INR', ?, ?)
                    """,
                    (bid, reconciliation_id, bdate, bdesc, bdesc, bamt, btype, bref, bbal, prov, brow)
                )

            comp_data = [
                ("TXN_COMP_01", "2026-10-01", "Amazon Seller Services India", 1250.00, "DEBIT", "UPI0092817", 1),
                ("TXN_COMP_02", "2026-10-02", "October Payroll Acme Corp", 85000.00, "CREDIT", "SAL992810", 2),
                ("TXN_COMP_03", "2026-10-02", "ABC Logistics Delivery Charges", 48500.00, "DEBIT", "NEFT881920", 3),
                ("TXN_COMP_04", "2026-10-06", "Amazon Web Services Hosting", 25000.00, "DEBIT", "AWS771920", 4),
                ("TXN_COMP_05", "2026-10-07", "Office Supplies India", 4000.00, "DEBIT", "OFF99120", 5),
                ("TXN_COMP_06", "2026-10-08", "Vendor Part A Payment", 10000.00, "DEBIT", "VEND-A", 6),
                ("TXN_COMP_07", "2026-10-08", "Vendor Part B Payment", 15000.00, "DEBIT", "VEND-B", 7),
                ("TXN_COMP_08", "2026-10-09", "Client Retainer Invoice #1042", 50000.00, "CREDIT", "INV1042", 8),
            ]

            for cid, cdate, cdesc, camt, ctype, cref, crow in comp_data:
                prov = json.dumps({"file_id": "FILE_COMP_TALLY_01", "filename": "Tally_General_Ledger_Oct.xlsx", "page": 1, "row": crow})
                conn.execute(
                    """
                    INSERT INTO transactions (
                        id, reconciliation_id, source_id, source_type, parse_job_id,
                        date, description, description_original, amount, type, reference, balance,
                        currency, provenance, source_row
                    ) VALUES (?, ?, 'SRC_DEMO_COMP', 'ACCOUNTING_LEDGER', 'JOB_DEMO_01', ?, ?, ?, ?, ?, ?, NULL, 'INR', ?, ?)
                    """,
                    (cid, reconciliation_id, cdate, cdesc, cdesc, camt, ctype, cref, prov, crow)
                )

        conn.close()
        return {
            "reconciliation_id": reconciliation_id,
            "bank_count": len(bank_data),
            "company_count": len(comp_data),
            "status": "SEEDED",
            "message": f"Successfully loaded {len(bank_data)} Bank Statement transactions and {len(comp_data)} Accounting Ledger transactions."
        }

