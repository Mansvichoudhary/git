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
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            sha256_hash TEXT NOT NULL,
            status TEXT DEFAULT 'UPLOADED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS parse_jobs (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            status TEXT NOT NULL,
            parser_type TEXT,
            total_rows INTEGER DEFAULT 0,
            valid_rows INTEGER DEFAULT 0,
            warning_rows INTEGER DEFAULT 0,
            error_rows INTEGER DEFAULT 0,
            mapping_config TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files (id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            parse_job_id TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            description_original TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            reference TEXT,
            balance REAL,
            currency TEXT DEFAULT 'INR',
            source_row INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parse_job_id) REFERENCES parse_jobs (id)
        );

        CREATE TABLE IF NOT EXISTS parse_errors (
            id TEXT PRIMARY KEY,
            parse_job_id TEXT NOT NULL,
            row_number INTEGER,
            field TEXT,
            raw_value TEXT,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parse_job_id) REFERENCES parse_jobs (id)
        );
        """)
    conn.close()
