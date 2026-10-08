import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pypdf

logger = logging.getLogger("finagent.ocr")

def parse_scanned_pdf(file_path: Path) -> Tuple[int, List[str], List[Dict[str, Any]]]:
    """
    OCR pipeline for scanned PDF statements.
    Extracts embedded page images or invokes OCR text reconstruction.
    Falls back gracefully to OCR text extraction or structured line recovery.
    """
    logger.info(f"Initiating OCR pipeline for scanned document: {file_path}")
    headers = ["Date", "Description", "Debit", "Credit", "Reference", "Balance"]
    raw_rows: List[Dict[str, Any]] = []

    # Attempt pytesseract or paddleocr if installed
    ocr_available = False
    try:
        import pytesseract
        from PIL import Image
        ocr_available = True
    except ImportError:
        pass

    # Extract pages via pypdf
    try:
        reader = pypdf.PdfReader(str(file_path))
        extracted_lines = []

        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                extracted_lines.extend(text.splitlines())
            elif ocr_available and page.images:
                for img in page.images:
                    import io
                    pil_img = Image.open(io.BytesIO(img.data))
                    ocr_text = pytesseract.image_to_string(pil_img)
                    extracted_lines.extend(ocr_text.splitlines())

        # If textual lines were obtained via OCR or hybrid text
        for line in extracted_lines:
            tokens = [t.strip() for t in line.split() if t.strip()]
            if len(tokens) >= 3 and any(char.isdigit() for char in tokens[0]):
                raw_rows.append({
                    "Date": tokens[0],
                    "Description": " ".join(tokens[1:-2]) if len(tokens) > 3 else tokens[1],
                    "Debit": tokens[-2] if "DR" in line.upper() else "",
                    "Credit": tokens[-2] if "CR" in line.upper() or "DR" not in line.upper() else "",
                    "Reference": tokens[-1] if len(tokens) > 4 else "",
                    "Balance": ""
                })
    except Exception as e:
        logger.error(f"Error during OCR extraction: {str(e)}")

    # Return standard headers and parsed records
    return 0, headers, raw_rows
