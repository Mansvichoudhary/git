from pathlib import Path
from typing import List, Dict, Any, Tuple
import openpyxl
from app.parser.csv_parser import TABLE_HEADER_KEYWORDS


def parse_xlsx_file(file_path: Path) -> Tuple[int, List[str], List[Dict[str, Any]]]:
    """
    Parses Excel XLSX files with header offset detection.
    Returns (header_row_index, header_columns, list_of_raw_rows).
    """
    wb = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
    sheet = wb.active

    all_rows: List[List[Any]] = []
    for row in sheet.iter_rows(values_only=True):
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            all_rows.append(list(row))

    wb.close()

    if not all_rows:
        return 0, [], []

    # Detect header row index
    header_idx = 0
    max_matches = 0

    for idx, row in enumerate(all_rows[:25]):
        str_cells = [str(cell).lower().strip() for cell in row if cell is not None]
        matches = sum(
            1 for c in str_cells
            if any(kw in c for kw in TABLE_HEADER_KEYWORDS)
        )
        if matches > max_matches:
            max_matches = matches
            header_idx = idx

    header_row = all_rows[header_idx]
    headers = [str(c).strip() for c in header_row if c is not None and str(c).strip()]

    raw_rows: List[Dict[str, Any]] = []
    num_headers = len(headers)

    for row in all_rows[header_idx + 1:]:
        row_dict = {}
        for col_idx in range(min(num_headers, len(row))):
            val = row[col_idx]
            col_name = headers[col_idx]
            row_dict[col_name] = str(val).strip() if val is not None else ""
        
        if any(v for v in row_dict.values()):
            raw_rows.append(row_dict)

    return header_idx, headers, raw_rows
