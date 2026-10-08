import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PARSED_DIR = DATA_DIR / "parsed"
DB_PATH = DATA_DIR / "finagent_ingestion.db"

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PARSED_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".pdf"}

# Standard Bank Column Alias Dictionary
CANONICAL_FIELD_ALIASES = {
    "date": [
        "date", "txn date", "transaction date", "value date", "posting date",
        "trans date", "booking date", "entry date", "activity date", "statement date"
    ],
    "description": [
        "description", "particulars", "narration", "transaction remarks",
        "details", "transaction details", "memo", "payee", "counterparty",
        "merchant", "narrative", "transaction description"
    ],
    "debit": [
        "debit", "dr amount", "dr", "withdrawal", "debit amount",
        "withdrawals", "debit(inr)", "payment", "spent", "dr amt"
    ],
    "credit": [
        "credit", "cr amount", "cr", "deposit", "credit amount",
        "deposits", "credit(inr)", "received", "cr amt"
    ],
    "amount": [
        "amount", "net amount", "transaction amount", "trans amount", "total", "sum"
    ],
    "type": [
        "type", "dr/cr", "transaction type", "cr/dr", "d/c", "txn type"
    ],
    "reference": [
        "reference", "ref no", "reference number", "utr", "cheque no",
        "chq no", "chq/ref no", "transaction id", "txn id", "ref id",
        "urn", "instrument id", "check #"
    ],
    "balance": [
        "balance", "closing balance", "available balance", "running balance",
        "account balance", "net balance", "bal"
    ],
    "currency": [
        "currency", "curr", "ccy"
    ]
}
