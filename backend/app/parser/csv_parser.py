import csv
import io
from pathlib import Path
from typing import List, Dict, Any, Tuple


TABLE_HEADER_KEYWORDS = [
    "date", "txn date", "transaction date", "value date",
    "particulars", "description", "narration", "details",
    "debit", "credit", "withdrawal", "deposit", "amount",
    "balance", "ref", "utr", "chq"
]


def detect_csv_delimiter(sample_text: str) -> str:
    """
    Detects delimiter among comma, tab, semicolon, or pipe.
    """
    delimiters = [",", "\t", ";", "|"]
    counts = {d: sample_text.count(d) for d in delimiters}
    best_del = max(counts, key=counts.get)
    return best_del if counts[best_del] > 0 else ","


def parse_csv_file(file_path: Path) -> Tuple[int, List[str], List[Dict[str, Any]]]:
    """
    Parses CSV/TSV with intelligent header offset detection.
    Returns (header_row_index, header_columns, list_of_raw_rows).
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    if not lines:
        return 0, [], []

    sample_block = "\n".join(lines[:15])
    delimiter = detect_csv_delimiter(sample_block)

    # Detect which line is the actual table header
    header_idx = 0
    max_keyword_matches = 0

    for idx, line in enumerate(lines[:25]):
        reader = csv.reader([line], delimiter=delimiter)
        try:
            tokens = next(reader)
        except StopIteration:
            continue
        
        matches = sum(
            1 for token in tokens
            if any(kw in token.lower().strip() for kw in TABLE_HEADER_KEYWORDS)
        )
        if matches > max_keyword_matches:
            max_keyword_matches = matches
            header_idx = idx

    # Parse CSV from detected header row onwards
    content_io = io.StringIO("\n".join(lines[header_idx:]))
    csv_reader = csv.DictReader(content_io, delimiter=delimiter)

    headers = [h.strip() for h in (csv_reader.fieldnames or []) if h and h.strip()]
    raw_rows: List[Dict[str, Any]] = []

    for row in csv_reader:
        cleaned_row = {k.strip(): v.strip() for k, v in row.items() if k and k.strip()}
        # Only add if row has at least some content
        if any(cleaned_row.values()):
            raw_rows.append(cleaned_row)

    return header_idx, headers, raw_rows
