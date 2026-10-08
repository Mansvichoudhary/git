import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pypdf
from app.parser.csv_parser import TABLE_HEADER_KEYWORDS


def parse_pdf_file(file_path: Path) -> Tuple[int, List[str], List[Dict[str, Any]]]:
    """
    Extracts text-based tables from PDF bank statements.
    Detects table lines and aligns tokens to headers.
    """
    reader = pypdf.PdfReader(str(file_path))
    all_lines: List[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                all_lines.append(clean)

    if not all_lines:
        return 0, [], []

    # Detect header line
    header_idx = 0
    max_matches = 0

    for idx, line in enumerate(all_lines[:30]):
        line_lower = line.lower()
        matches = sum(1 for kw in TABLE_HEADER_KEYWORDS if kw in line_lower)
        if matches > max_matches:
            max_matches = matches
            header_idx = idx

    header_line = all_lines[header_idx]
    # Split header line into tokens by multi-space or tab
    headers = [t.strip() for t in re.split(r"\s{2,}|\t", header_line) if t.strip()]

    if len(headers) < 2:
        # Fallback to standard financial columns
        headers = ["Date", "Description", "Debit", "Credit", "Balance"]

    raw_rows: List[Dict[str, Any]] = []

    for line in all_lines[header_idx + 1:]:
        tokens = [t.strip() for t in re.split(r"\s{2,}|\t", line) if t.strip()]
        if len(tokens) >= 2:
            row_dict = {}
            for i, col in enumerate(headers):
                row_dict[col] = tokens[i] if i < len(tokens) else ""
            raw_rows.append(row_dict)

    return header_idx, headers, raw_rows
