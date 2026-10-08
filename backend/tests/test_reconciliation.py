import unittest
import sys
from pathlib import Path
from decimal import Decimal
from datetime import date

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import init_db
from app.schemas.transaction import CanonicalTransaction
from app.reconciliation.scorer import (
    calculate_amount_score,
    calculate_date_score,
    calculate_description_score,
    calculate_match_score
)
from app.reconciliation.matching_engine import ReconciliationMatchingEngine
from app.reconciliation.anomaly_detector import ReconciliationAnomalyDetector
from app.reconciliation.ai_investigator import AIInvestigationAgent
from app.services.reconciliation_service import ReconciliationService


class TestReconciliationProcess02(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def _make_txn(self, id_val, dt_val, desc, amt, t_type="DEBIT", ref=None, src_type="BANK_STATEMENT"):
        return CanonicalTransaction(
            id=id_val,
            reconciliation_id="REC_TEST",
            source_id="SRC_TEST",
            source_type=src_type,
            date=dt_val,
            description=desc,
            description_original=desc,
            amount=Decimal(str(amt)),
            type=t_type,
            reference=ref,
            currency="INR",
            provenance={"file": "test", "row": 1}
        )

    def test_01_exact_match(self):
        """Amount, Date, Type, Description, Ref identical -> 100% confidence MATCHED."""
        b = self._make_txn("B1", date(2026, 10, 10), "AWS CLOUD SERVICES", "15420.00", "DEBIT", "UTR12345")
        c = self._make_txn("C1", date(2026, 10, 10), "AWS CLOUD SERVICES", "15420.00", "DEBIT", "UTR12345")

        matches, unmatched_c = ReconciliationMatchingEngine.execute_matching_pipeline("R1", [b], [c])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].status, "MATCHED")
        self.assertEqual(matches[0].match_type, "EXACT")
        self.assertGreaterEqual(matches[0].confidence, 0.95)
        self.assertEqual(len(unmatched_c), 0)

    def test_02_strong_reference_match(self):
        """Same UTR reference and amount, slight description variation -> MATCHED."""
        b = self._make_txn("B2", date(2026, 10, 10), "UPI-ZOMATO-ORDER-9812", "480.00", "DEBIT", "UTR98231")
        c = self._make_txn("C2", date(2026, 10, 10), "Zomato Meals Expense", "480.00", "DEBIT", "UTR98231")

        matches, _ = ReconciliationMatchingEngine.execute_matching_pipeline("R2", [b], [c])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].status, "MATCHED")
        self.assertEqual(matches[0].match_type, "REFERENCE")

    def test_03_fuzzy_description_and_date_tolerance(self):
        """Amount matches, description fuzzy, date differs by 2 days -> PROBABLE_MATCH."""
        b = self._make_txn("B3", date(2026, 10, 10), "AMAZON WEB SERVICES INDIA", "15420.00", "DEBIT")
        c = self._make_txn("C3", date(2026, 10, 12), "AWS Cloud Services", "15420.00", "DEBIT")

        matches, _ = ReconciliationMatchingEngine.execute_matching_pipeline("R3", [b], [c])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].status, "PROBABLE_MATCH")
        self.assertEqual(matches[0].date_difference_days, 2)
        self.assertGreaterEqual(matches[0].confidence, 0.75)

    def test_04_direction_conflict_prevention(self):
        """Debit vs Credit must NEVER match (hard financial constraint)."""
        b = self._make_txn("B4", date(2026, 10, 10), "CLIENT SETTLEMENT", "25000.00", "DEBIT")
        c = self._make_txn("C4", date(2026, 10, 10), "CLIENT SETTLEMENT", "25000.00", "CREDIT")

        matches, unmatched_c = ReconciliationMatchingEngine.execute_matching_pipeline("R4", [b], [c])
        self.assertEqual(matches[0].status, "UNMATCHED")
        self.assertEqual(len(unmatched_c), 1)

    def test_05_one_to_one_matching_protection(self):
        """Prevent double assignment of the same company transaction."""
        b1 = self._make_txn("B5_1", date(2026, 10, 10), "OFFICE CHAIRS PURCHASE", "5000.00")
        b2 = self._make_txn("B5_2", date(2026, 10, 10), "OFFICE CHAIRS PURCHASE", "5000.00")
        c1 = self._make_txn("C5_1", date(2026, 10, 10), "OFFICE CHAIRS PURCHASE", "5000.00")

        matches, _ = ReconciliationMatchingEngine.execute_matching_pipeline("R5", [b1, b2], [c1])
        matched_items = [m for m in matches if m.status == "MATCHED"]
        unmatched_items = [m for m in matches if m.status == "UNMATCHED"]
        self.assertEqual(len(matched_items), 1)
        self.assertEqual(len(unmatched_items), 1)

    def test_06_composite_partial_matching(self):
        """1 bank transaction of 10,000 matches 2 company split transactions (4,000 + 6,000)."""
        b = self._make_txn("B6", date(2026, 10, 10), "VENDOR BULK CONSOLIDATED", "10000.00")
        c1 = self._make_txn("C6_1", date(2026, 10, 10), "Vendor Part 1", "4000.00")
        c2 = self._make_txn("C6_2", date(2026, 10, 10), "Vendor Part 2", "6000.00")

        matches, unmatched_c = ReconciliationMatchingEngine.execute_matching_pipeline("R6", [b], [c1, c2])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].status, "PROBABLE_MATCH")
        self.assertEqual(matches[0].match_type, "COMPOSITE")
        self.assertEqual(len(unmatched_c), 0)

    def test_07_anomaly_detection_duplicates_and_missing(self):
        """Detect bank duplicate charges and missing transactions on both sides."""
        b_dup1 = self._make_txn("B7_1", date(2026, 10, 15), "ABC SUPPLIERS", "25000.00")
        b_dup2 = self._make_txn("B7_2", date(2026, 10, 15), "ABC SUPPLIERS", "25000.00")
        b_missing = self._make_txn("B7_3", date(2026, 10, 16), "UNKNOWN BANK FEE", "750.00")
        c_missing = self._make_txn("C7_1", date(2026, 10, 18), "UNPRESENTED CHEQUE", "12000.00")

        matches, unmatched_c = ReconciliationMatchingEngine.execute_matching_pipeline(
            "R7", [b_dup1, b_dup2, b_missing], [c_missing]
        )
        anomalies = ReconciliationAnomalyDetector.detect_anomalies(
            "R7", matches, [b_dup1, b_dup2, b_missing], [c_missing], unmatched_c
        )

        anom_types = [a.type for a in anomalies]
        self.assertIn("DUPLICATE_TRANSACTION", anom_types)
        self.assertIn("MISSING_IN_COMPANY", anom_types)
        self.assertIn("MISSING_IN_BANK", anom_types)

    def test_08_ai_investigation_layer(self):
        """Verify AI Forensic Investigation returns structured findings and risk scoring."""
        b = self._make_txn("B8", date(2026, 10, 10), "ABC LOGISTICS", "48500.00")
        c = self._make_txn("C8", date(2026, 10, 12), "ABC Logistics Services", "48500.00")

        matches, unmatched_c = ReconciliationMatchingEngine.execute_matching_pipeline("R8", [b], [c])
        anomalies = ReconciliationAnomalyDetector.detect_anomalies("R8", matches, [b], [c], unmatched_c)

        self.assertGreaterEqual(len(anomalies), 1)
        anom = anomalies[0]
        inv = AIInvestigationAgent.investigate_anomaly(anom)

        self.assertIsNotNone(inv.finding)
        self.assertIsNotNone(inv.conclusion)
        self.assertIn(inv.risk, ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
        self.assertGreaterEqual(inv.confidence, 0.70)
        self.assertGreaterEqual(len(inv.evidence), 1)


if __name__ == "__main__":
    unittest.main()
