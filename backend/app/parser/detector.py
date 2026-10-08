import os
from pathlib import Path
from typing import Dict, Any, Tuple
import pypdf


def detect_file_format(file_path: Path) -> Dict[str, Any]:
    """
    Sniffs magic bytes, file extensions, and internal structure.
    Determines whether file is CSV, XLSX, PDF_TEXT, or PDF_OCR.
    """
    file_size = os.path.getsize(file_path)
    extension = file_path.suffix.lower()

    with open(file_path, "rb") as f:
        magic_bytes = f.read(16)

    # 1. PDF Sniffing
    if magic_bytes.startswith(b"%PDF-") or extension == ".pdf":
        is_scanned = check_if_scanned_pdf(file_path)
        return {
            "file_type": "PDF_OCR" if is_scanned else "PDF_TEXT",
            "mime_type": "application/pdf",
            "extension": extension,
            "size": file_size,
            "is_scanned": is_scanned
        }

    # 2. XLSX Sniffing (Zip format PK\x03\x04)
    if magic_bytes.startswith(b"PK\x03\x04") or extension in [".xlsx", ".xlsm"]:
        return {
            "file_type": "XLSX",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "extension": extension,
            "size": file_size,
            "is_scanned": False
        }

    # 3. CSV / Tabular Plaintext
    if extension in [".csv", ".tsv", ".txt"]:
        return {
            "file_type": "CSV",
            "mime_type": "text/csv" if extension == ".csv" else "text/plain",
            "extension": extension,
            "size": file_size,
            "is_scanned": False
        }

    # Fallback attempt by reading text
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
            if "," in first_line or "\t" in first_line or ";" in first_line or "|" in first_line:
                return {
                    "file_type": "CSV",
                    "mime_type": "text/csv",
                    "extension": extension,
                    "size": file_size,
                    "is_scanned": False
                }
    except Exception:
        pass

    return {
        "file_type": "UNKNOWN",
        "mime_type": "application/octet-stream",
        "extension": extension,
        "size": file_size,
        "is_scanned": False
    }


def check_if_scanned_pdf(file_path: Path) -> bool:
    """
    Checks if a PDF has selectable textual content or is mostly raster images.
    """
    try:
        reader = pypdf.PdfReader(str(file_path))
        if len(reader.pages) == 0:
            return True
        
        total_chars = 0
        pages_to_check = min(3, len(reader.pages))
        for i in range(pages_to_check):
            text = reader.pages[i].extract_text() or ""
            total_chars += len(text.strip())
        
        # If less than 50 text characters across first 3 pages, it's likely scanned
        return total_chars < 50
    except Exception:
        return True
