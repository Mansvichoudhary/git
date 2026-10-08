from pathlib import Path
from typing import List, Dict, Any, Tuple
from app.parser.csv_parser import parse_csv_file
from app.parser.xlsx_parser import parse_xlsx_file
from app.parser.pdf_parser import parse_pdf_file
from app.parser.ocr import parse_scanned_pdf


def extract_raw_tabular_data(
    file_path: Path,
    parser_type: str
) -> Tuple[int, List[str], List[Dict[str, Any]]]:
    """
    Unified extraction router. Dispatches to the appropriate parser
    based on detected format (CSV, XLSX, PDF_TEXT, or PDF_OCR).
    Produces intermediate unmapped tabular records.
    """
    p_type = parser_type.upper()
    if p_type == "CSV":
        return parse_csv_file(file_path)
    elif p_type == "XLSX":
        return parse_xlsx_file(file_path)
    elif p_type == "PDF_TEXT" or p_type == "PDF":
        return parse_pdf_file(file_path)
    elif p_type == "PDF_OCR" or p_type == "SCANNED_PDF":
        return parse_scanned_pdf(file_path)
    else:
        # Default fallback attempt as CSV
        return parse_csv_file(file_path)
