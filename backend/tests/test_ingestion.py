import unittest
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal
from datetime import date

from app.core.database import init_db
from app.parser.normalizer import (
    normalize_date,
    clean_amount_string,
    normalize_transaction_type_and_amount
)
from app.parser.mapper import infer_column_mappings
from app.parser.csv_parser import parse_csv_file
from app.parser.validator import validate_and_build_canonical_transaction, generate_deterministic_id
from app.services.ingestion_service import IngestionService


class TestDataIngestionEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_date_normalization(self):
        """Verify various multi-bank date representations map to ISO date."""
        self.assertEqual(normalize_date("01/10/2026"), date(2026, 10, 1))
        self.assertEqual(normalize_date("01-Oct-2026"), date(2026, 10, 1))
        self.assertEqual(normalize_date("2026-10-01"), date(2026, 10, 1))
        self.assertEqual(normalize_date("01/10/2026 14:30:00"), date(2026, 10, 1))
        self.assertIsNone(normalize_date("INVALID_DATE"))

    def test_amount_and_currency_normalization(self):
        """Verify Indian comma formatting, currency symbols, and negatives."""
        amt, hint = clean_amount_string("₹1,50,000.00")
        self.assertEqual(amt, Decimal("150000.00"))
        
        amt_dr, hint_dr = clean_amount_string("1250.00 DR")
        self.assertEqual(amt_dr, Decimal("1250.00"))
        self.assertEqual(hint_dr, "DEBIT")

        amt_paren, hint_paren = clean_amount_string("(2,450.00)")
        self.assertEqual(amt_paren, Decimal("2450.00"))
        self.assertEqual(hint_paren, "DEBIT")

    def test_debit_credit_type_resolution(self):
        """Verify 2-column model resolution."""
        amt, txn_type, err = normalize_transaction_type_and_amount(
            debit_val="1250.00", credit_val=""
        )
        self.assertEqual(amt, Decimal("1250.00"))
        self.assertEqual(txn_type, "DEBIT")
        self.assertIsNone(err)

        amt_cr, type_cr, err_cr = normalize_transaction_type_and_amount(
            debit_val=None, credit_val="85,000.00"
        )
        self.assertEqual(amt_cr, Decimal("85000.00"))
        self.assertEqual(type_cr, "CREDIT")

    def test_csv_header_offset_detection(self):
        """Ensure parser skips bank branch/account metadata and lands on table header."""
        fixture_path = Path(__file__).parent / "fixtures" / "sample_hdfc_bank_statement.csv"
        header_idx, headers, rows = parse_csv_file(fixture_path)
        
        self.assertGreaterEqual(header_idx, 3)
        self.assertIn("Date", headers)
        self.assertIn("Narration", headers)
        self.assertEqual(len(rows), 7)

    def test_end_to_end_sbi_with_errors_and_warnings(self):
        """Test full pipeline on statement containing Indian commas, 1 warning, and 1 error."""
        fixture_path = Path(__file__).parent / "fixtures" / "sample_sbi_statement.csv"
        with open(fixture_path, "rb") as f:
            content = f.read()

        job_info = IngestionService.create_upload_job("sample_sbi.csv", content)
        job_id = job_info["job_id"]

        # Run pipeline
        res = IngestionService.execute_pipeline(job_id=job_id)
        
        self.assertEqual(res["total_rows"], 5)
        self.assertEqual(res["valid_rows"], 4)  # 4 valid, 1 invalid date
        self.assertEqual(res["error_rows"], 1)  # 1 row with INVALID_DATE_ROW
        self.assertGreaterEqual(res["warning_rows"], 1)  # Office rent missing ref no

        # Export canonical statement package
        pkg = IngestionService.export_canonical_statement_package(job_id)
        self.assertEqual(len(pkg.transactions), 4)
        self.assertTrue(pkg.transactions[0].id.startswith("TXN_"))
        self.assertEqual(pkg.transactions[0].amount, Decimal("1250.00"))
        self.assertEqual(pkg.transactions[0].type, "DEBIT")

    def test_xlsx_pipeline(self):
        """Verify full ingestion pipeline on multi-row XLSX file."""
        fixture_path = Path(__file__).parent / "fixtures" / "sample_icici_statement.xlsx"
        with open(fixture_path, "rb") as f:
            content = f.read()

        job_info = IngestionService.create_upload_job("sample_icici.xlsx", content)
        job_id = job_info["job_id"]
        self.assertEqual(job_info["mime_type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Execute
        res = IngestionService.execute_pipeline(job_id=job_id)
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["total_rows"], 4)
        self.assertEqual(res["valid_rows"], 4)
        self.assertEqual(res["error_rows"], 0)

        # Verify transactions
        txns = IngestionService.get_transactions(job_id)
        self.assertEqual(len(txns), 4)
        self.assertEqual(txns[0]["description"], "NETFLIX SUBSCRIPTION MUMBAI")
        self.assertEqual(txns[0]["type"], "DEBIT")
        self.assertEqual(txns[1]["description"], "CONSULTING FEES INFLOW")
        self.assertEqual(txns[1]["type"], "CREDIT")

    def test_fuzzy_column_mapping(self):
        """Verify RapidFuzz token matching for unorthodox column names."""
        unorthodox_headers = ["Transact Date", "Narrative Details", "Money Out Dr", "Money In Cr", "Net Bal"]
        sample_rows = [
            {"Transact Date": "01/10/2026", "Narrative Details": "Test", "Money Out Dr": "100", "Money In Cr": "", "Net Bal": "5000"}
        ]
        mappings, score = infer_column_mappings(unorthodox_headers, sample_rows)
        mapping_dict = {m.source_column: m.target_field for m in mappings}
        self.assertEqual(mapping_dict.get("Transact Date"), "date")
        self.assertEqual(mapping_dict.get("Narrative Details"), "description")
        self.assertGreaterEqual(score, 0.7)

    def test_company_and_reconciliation_hierarchy(self):
        """Verify multi-tenant company and reconciliation creation (Sections 5 & 6)."""
        from app.schemas.ingestion import CompanyCreate, ReconciliationCreate, SourceCreate
        comp = IngestionService.create_company(CompanyCreate(
            company_name="Apex Logistics Ltd",
            legal_name="Apex Logistics Solutions India Pvt Ltd",
            industry="Transportation"
        ))
        self.assertTrue(comp.id.startswith("COMP_"))
        self.assertEqual(comp.company_name, "Apex Logistics Ltd")

        # Create Reconciliation
        rec = IngestionService.create_reconciliation(ReconciliationCreate(
            company_id=comp.id,
            name="Q3 Bank Reconciliation",
            period_start="2026-07-01",
            period_end="2026-09-30"
        ))
        self.assertTrue(rec.id.startswith("REC_"))
        self.assertEqual(rec.company_id, comp.id)

        # Add multiple sources
        src1 = IngestionService.create_source(SourceCreate(
            reconciliation_id=rec.id,
            source_type="BANK_STATEMENT",
            name="HDFC Current Account"
        ))
        src2 = IngestionService.create_source(SourceCreate(
            reconciliation_id=rec.id,
            source_type="ACCOUNTING_LEDGER",
            name="Tally Prime ERP Ledger"
        ))
        sources = IngestionService.get_sources(rec.id)
        self.assertEqual(len(sources), 2)

    def test_duplicate_file_detection(self):
        """Verify SHA-256 duplicate fingerprint detection (Section 9)."""
        import uuid
        unique_rec_id = f"REC_DUP_TEST_{uuid.uuid4().hex[:6]}"
        fixture_path = Path(__file__).parent / "fixtures" / "sample_hdfc_bank_statement.csv"
        with open(fixture_path, "rb") as f:
            content = f.read()

        # Upload first time in this scope
        job1 = IngestionService.create_upload_job("hdfc1.csv", content, reconciliation_id=unique_rec_id)
        self.assertFalse(job1["is_duplicate"])

        # Upload exact same content second time in same scope
        job2 = IngestionService.create_upload_job("hdfc1_copy.csv", content, reconciliation_id=unique_rec_id)
        self.assertTrue(job2["is_duplicate"])

    def test_financial_control_totals_and_provenance(self):
        """Verify financial control totals calculation and transaction provenance (Sections 19 & 22)."""
        fixture_path = Path(__file__).parent / "fixtures" / "sample_hdfc_bank_statement.csv"
        with open(fixture_path, "rb") as f:
            content = f.read()

        job_info = IngestionService.create_upload_job("hdfc_control.csv", content)
        res = IngestionService.execute_pipeline(job_info["job_id"])

        # Control totals verification
        ctrl = res["control_totals"]
        self.assertGreater(ctrl.total_debits, Decimal("0.00"))
        self.assertGreater(ctrl.total_credits, Decimal("0.00"))
        self.assertEqual(ctrl.transaction_count, 7)

        # Provenance check
        txns = IngestionService.get_transactions(job_info["job_id"])
        self.assertGreaterEqual(len(txns), 7)
        first_txn = txns[0]
        self.assertIn("provenance", first_txn)
        self.assertEqual(first_txn["provenance"]["filename"], "hdfc_control.csv")
        self.assertEqual(first_txn["provenance"]["row"], 1)

    def test_persistent_mapping_rule_learning(self):
        """Verify persistent mapping rules memory (Section 16)."""
        # Save custom mapping
        IngestionService.execute_pipeline(
            job_id="dummy_job" if False else [k for k in [""]] * 0 or "JOB_TEST",
            custom_mappings={"description": "Special Narration Col"},
            source_type="CUSTOM_TEST_SOURCE",
            remember_rules=True
        ) if False else None

        # Directly verify mapping persistence via execution
        fixture_path = Path(__file__).parent / "fixtures" / "sample_hdfc_bank_statement.csv"
        with open(fixture_path, "rb") as f:
            content = f.read()
        job = IngestionService.create_upload_job("test_learn.csv", content)
        IngestionService.execute_pipeline(
            job["job_id"],
            custom_mappings={"description": "Narration"},
            source_type="BANK_STATEMENT",
            remember_rules=True
        )
        
        # Subsequent detection should reflect learned rule
        sugg = IngestionService.detect_and_suggest_mappings(job["job_id"])
        narr_item = next((m for m in sugg["suggested_mappings"] if m.source_column == "Narration"), None)
        self.assertIsNotNone(narr_item)
        self.assertEqual(narr_item.target_field, "description")


if __name__ == "__main__":
    unittest.main()
