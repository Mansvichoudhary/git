import sqlite3
from typing import Generator
from app.core.config import DB_PATH


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    with conn:
        conn.executescript("""
        -- 1. Multi-Tenant Companies
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            legal_name TEXT,
            industry TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            country TEXT DEFAULT 'India',
            timezone TEXT DEFAULT 'Asia/Kolkata',
            base_currency TEXT DEFAULT 'INR',
            logo_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 2. Company Members & Roles
        CREATE TABLE IF NOT EXISTS company_members (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT DEFAULT 'FINANCE_MANAGER',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies (id)
        );

        -- 3. Reconciliations Context
        CREATE TABLE IF NOT EXISTS reconciliations (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            name TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            status TEXT DEFAULT 'INGESTING',
            created_by TEXT DEFAULT 'system',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies (id)
        );

        -- 4. Financial Sources (Bank Statement, Accounting Ledger, etc.)
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            reconciliation_id TEXT NOT NULL,
            source_type TEXT NOT NULL, -- BANK_STATEMENT, ACCOUNTING_LEDGER, PAYMENT_REGISTER, etc.
            name TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reconciliation_id) REFERENCES reconciliations (id)
        );

        -- 5. Files Metadata & SHA-256 Deduplication
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            source_id TEXT,
            reconciliation_id TEXT,
            filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_hash TEXT NOT NULL, -- SHA-256 fingerprint
            storage_path TEXT NOT NULL,
            status TEXT DEFAULT 'UPLOADED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES sources (id),
            FOREIGN KEY (reconciliation_id) REFERENCES reconciliations (id)
        );

        -- 6. Parse Execution Jobs with Control Totals
        CREATE TABLE IF NOT EXISTS parse_jobs (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            status TEXT NOT NULL, -- UPLOADED, DETECTING, EXTRACTING, MAPPING, NEEDS_REVIEW, NORMALIZING, VALIDATING, CONTROL_CHECK, COMPLETED, FAILED
            parser_type TEXT,
            parser_version TEXT DEFAULT '1.0.0',
            total_rows INTEGER DEFAULT 0,
            valid_rows INTEGER DEFAULT 0,
            warning_rows INTEGER DEFAULT 0,
            error_rows INTEGER DEFAULT 0,
            opening_balance REAL,
            closing_balance REAL,
            total_debits REAL DEFAULT 0,
            total_credits REAL DEFAULT 0,
            control_difference REAL DEFAULT 0,
            control_status TEXT DEFAULT 'NOT_APPLICABLE',
            mapping_config TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files (id)
        );

        -- 7. Canonical Normalized Transactions with Provenance
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            reconciliation_id TEXT,
            source_id TEXT,
            source_type TEXT DEFAULT 'BANK_STATEMENT',
            parse_job_id TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            description_original TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL, -- DEBIT, CREDIT
            reference TEXT,
            balance REAL,
            currency TEXT DEFAULT 'INR',
            account_id TEXT,
            transaction_id TEXT,
            external_id TEXT,
            invoice_id TEXT,
            vendor TEXT,
            customer TEXT,
            provenance TEXT, -- JSON containing file_id, filename, page, row
            source_row INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parse_job_id) REFERENCES parse_jobs (id)
        );

        -- 8. Error Queue Ledger
        CREATE TABLE IF NOT EXISTS parse_errors (
            id TEXT PRIMARY KEY,
            parse_job_id TEXT NOT NULL,
            row_number INTEGER,
            page_number INTEGER DEFAULT 1,
            field TEXT,
            value TEXT,
            severity TEXT NOT NULL, -- WARNING, ERROR, FATAL
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parse_job_id) REFERENCES parse_jobs (id)
        );

        -- 9. Persistent Mapping Rules Memory
        CREATE TABLE IF NOT EXISTS mapping_rules (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_identifier TEXT, -- Bank name or format keyword (e.g. HDFC, ICICI, SBI)
            source_column TEXT NOT NULL,
            target_field TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 10. Reconciliation Runs (Process 02)
        CREATE TABLE IF NOT EXISTS reconciliation_runs (
            id TEXT PRIMARY KEY,
            reconciliation_id TEXT NOT NULL,
            bank_source_id TEXT,
            company_source_id TEXT,
            status TEXT NOT NULL, -- READY, MATCHING, ANALYZING, INVESTIGATING, REVIEW_REQUIRED, COMPLETED, FAILED
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reconciliation_id) REFERENCES reconciliations (id)
        );

        -- 11. Transaction Matches (Process 02)
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            reconciliation_run_id TEXT NOT NULL,
            bank_transaction_id TEXT,
            company_transaction_id TEXT,
            status TEXT NOT NULL, -- MATCHED, PROBABLE_MATCH, UNMATCHED
            match_type TEXT NOT NULL, -- EXACT, REFERENCE, FUZZY, DATE_TOLERANCE, COMPOSITE
            confidence REAL NOT NULL,
            amount_difference REAL DEFAULT 0,
            date_difference_days INTEGER DEFAULT 0,
            amount_score REAL DEFAULT 0,
            date_score REAL DEFAULT 0,
            description_score REAL DEFAULT 0,
            reference_score REAL DEFAULT 0,
            type_score REAL DEFAULT 0,
            reasons TEXT, -- JSON array of string reasons
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reconciliation_run_id) REFERENCES reconciliation_runs (id)
        );

        -- 12. Financial Anomalies (Process 02)
        CREATE TABLE IF NOT EXISTS anomalies (
            id TEXT PRIMARY KEY,
            reconciliation_run_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            candidate_transaction_id TEXT,
            type TEXT NOT NULL, -- DUPLICATE_TRANSACTION, DATE_MISMATCH, AMOUNT_MISMATCH, MISSING_IN_COMPANY, MISSING_IN_BANK, etc.
            severity TEXT NOT NULL, -- LOW, MEDIUM, HIGH, CRITICAL
            status TEXT DEFAULT 'PENDING', -- PENDING, INVESTIGATING, CONFIRMED, REJECTED, RESOLVED
            amount_difference REAL DEFAULT 0,
            date_difference_days INTEGER DEFAULT 0,
            evidence TEXT, -- JSON array of evidence strings
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reconciliation_run_id) REFERENCES reconciliation_runs (id)
        );

        -- 13. AI Investigations (Process 02)
        CREATE TABLE IF NOT EXISTS investigations (
            id TEXT PRIMARY KEY,
            anomaly_id TEXT NOT NULL,
            finding TEXT NOT NULL,
            conclusion TEXT NOT NULL,
            confidence REAL NOT NULL,
            risk TEXT NOT NULL, -- LOW, MEDIUM, HIGH, CRITICAL
            evidence TEXT, -- JSON array of evidence bullets
            recommended_action TEXT NOT NULL,
            ai_model TEXT DEFAULT 'gemini-1.5-flash',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (anomaly_id) REFERENCES anomalies (id)
        );

        -- 14. Human Reviews & Audit (Process 02)
        CREATE TABLE IF NOT EXISTS human_reviews (
            id TEXT PRIMARY KEY,
            anomaly_id TEXT NOT NULL,
            user_id TEXT DEFAULT 'auditor_user',
            action TEXT NOT NULL, -- CONFIRM_MATCH, MARK_UNMATCHED, MARK_DUPLICATE
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (anomaly_id) REFERENCES anomalies (id)
        );
        """)

        # Ensure default company and reconciliation exist for seamless out-of-the-box operation
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM companies LIMIT 1")
        if not cursor.fetchone():
            cursor.execute("""
            INSERT INTO companies (id, company_name, legal_name, industry, email, base_currency)
            VALUES ('COMP_DEMO_01', 'Acme FinTech Corp', 'Acme Financial Technologies Pvt Ltd', 'Fintech / Banking', 'finance@acme.corp', 'INR')
            """)
            cursor.execute("""
            INSERT INTO reconciliations (id, company_id, name, period_start, period_end, status)
            VALUES ('REC_DEMO_01', 'COMP_DEMO_01', 'October 2026 Monthly Bank & Ledger Reconciliation', '2026-10-01', '2026-10-31', 'INGESTING')
            """)
            cursor.execute("""
            INSERT INTO sources (id, reconciliation_id, source_type, name)
            VALUES ('SRC_DEMO_BANK', 'REC_DEMO_01', 'BANK_STATEMENT', 'Primary HDFC Current Account')
            """)
            cursor.execute("""
            INSERT INTO sources (id, reconciliation_id, source_type, name)
            VALUES ('SRC_DEMO_LEDGER', 'REC_DEMO_01', 'ACCOUNTING_LEDGER', 'Internal General Ledger')
            """)
    conn.close()
