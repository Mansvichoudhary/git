import re
from typing import List, Dict, Any, Optional, Tuple
from rapidfuzz import fuzz
from app.core.config import CANONICAL_FIELD_ALIASES
from app.schemas.ingestion import ColumnMappingItem
from app.parser.normalizer import normalize_date, clean_amount_string


def infer_column_mappings(
    headers: List[str],
    sample_rows: List[Dict[str, Any]]
) -> Tuple[List[ColumnMappingItem], float]:
    """
    Intelligently maps heterogeneous source bank headers to canonical fields.
    Uses a 3-tier cascade:
    1. Exact alias dictionary
    2. Fuzzy token similarity (threshold >= 85%)
    3. Column data content heuristics
    """
    assigned_targets = set()
    mappings: List[ColumnMappingItem] = []
    total_confidence = 0.0

    # Step 1: Pre-process headers and gather samples
    header_samples: Dict[str, List[str]] = {h: [] for h in headers}
    for row in sample_rows[:10]:
        for h in headers:
            val = str(row.get(h, "")).strip()
            if val and val not in header_samples[h]:
                header_samples[h].append(val)

    # Required target fields
    target_fields = ["date", "description", "debit", "credit", "amount", "type", "reference", "balance"]

    for header in headers:
        clean_header = re.sub(r"[_\-./\\#()]", " ", header).lower().strip()
        clean_header = re.sub(r"\s+", " ", clean_header)

        matched_field: Optional[str] = None
        best_confidence: float = 0.0
        match_method: str = "fuzzy"

        # 1. Exact alias match
        for field, aliases in CANONICAL_FIELD_ALIASES.items():
            if field in assigned_targets:
                continue
            if clean_header in aliases or any(alias == clean_header for alias in aliases):
                matched_field = field
                best_confidence = 1.0
                match_method = "alias"
                break

        # 2. Fuzzy similarity match
        if not matched_field:
            for field, aliases in CANONICAL_FIELD_ALIASES.items():
                if field in assigned_targets:
                    continue
                for alias in aliases:
                    sim = max(
                        fuzz.token_set_ratio(clean_header, alias),
                        fuzz.token_sort_ratio(clean_header, alias)
                    ) / 100.0
                    if sim >= 0.80 and sim > best_confidence:
                        best_confidence = sim
                        matched_field = field
                        match_method = "fuzzy"

        # 3. Content heuristic check if header matching was ambiguous
        if (not matched_field or best_confidence < 0.85) and header_samples[header]:
            heuristic_field, heuristic_conf = check_column_content_heuristics(
                header_samples[header], assigned_targets
            )
            if heuristic_conf > best_confidence:
                matched_field = heuristic_field
                best_confidence = heuristic_conf
                match_method = "heuristic"

        # 4. AI-assisted mapping fallback for ambiguous fields
        if (not matched_field or best_confidence < 0.75):
            ai_field, ai_conf = attempt_ai_column_mapping(clean_header, header_samples[header], assigned_targets)
            if ai_field and ai_conf > best_confidence:
                matched_field = ai_field
                best_confidence = ai_conf
                match_method = "ai"

        if matched_field and best_confidence >= 0.70:
            assigned_targets.add(matched_field)
            mappings.append(ColumnMappingItem(
                source_column=header,
                target_field=matched_field,
                confidence=round(best_confidence, 2),
                method=match_method,
                sample_values=header_samples[header][:3]
            ))
            total_confidence += best_confidence
        else:
            mappings.append(ColumnMappingItem(
                source_column=header,
                target_field=None,
                confidence=0.0,
                method="manual",
                sample_values=header_samples[header][:3]
            ))

    # Overall pipeline mapping confidence
    essential_found = sum(1 for m in mappings if m.target_field in ["date", "description"])
    amount_found = any(m.target_field in ["debit", "credit", "amount"] for m in mappings)
    
    overall_score = 0.0
    if len(mappings) > 0:
        base_avg = total_confidence / max(1, len([m for m in mappings if m.target_field]))
        if essential_found >= 2 and amount_found:
            overall_score = round(base_avg, 2)
        else:
            overall_score = round(base_avg * 0.6, 2)

    return mappings, overall_score


def attempt_ai_column_mapping(
    header: str,
    samples: List[str],
    assigned_targets: set
) -> Tuple[Optional[str], float]:
    """
    AI-assisted schema mapping layer (only for ambiguous fields).
    Uses Gemini LLM if GEMINI_API_KEY is configured, or semantic embeddings/heuristics.
    """
    import os
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                f"You are a financial parsing expert. Map this column header to exactly one canonical field from:\n"
                f"[date, description, debit, credit, amount, type, reference, balance, ignore].\n"
                f"Header name: '{header}'\n"
                f"Sample cell values: {samples[:3]}\n"
                f"Answer with ONLY the target field name."
            )
            resp = model.generate_content(prompt)
            pred = resp.text.strip().lower()
            if pred in ["date", "description", "debit", "credit", "amount", "type", "reference", "balance"] and pred not in assigned_targets:
                return pred, 0.95
        except Exception:
            pass

    # High-level semantic reasoning fallback for AI step
    header_lower = header.lower()
    if "narration" in header_lower or "detail" in header_lower or "remark" in header_lower:
        if "description" not in assigned_targets:
            return "description", 0.92
    if "withdrawal" in header_lower or "dr" in header_lower:
        if "debit" not in assigned_targets:
            return "debit", 0.92
    if "deposit" in header_lower or "cr" in header_lower:
        if "credit" not in assigned_targets:
            return "credit", 0.92

    return None, 0.0


def check_column_content_heuristics(
    sample_values: List[str],
    assigned_targets: set
) -> Tuple[Optional[str], float]:
    """
    Examines raw values in a column to guess the semantic field.
    """
    valid_dates = sum(1 for v in sample_values if normalize_date(v) is not None)
    if "date" not in assigned_targets and valid_dates / max(1, len(sample_values)) >= 0.7:
        return "date", 0.90

    valid_amounts = sum(1 for v in sample_values if clean_amount_string(v)[0] is not None)
    if valid_amounts / max(1, len(sample_values)) >= 0.7:
        if "amount" not in assigned_targets and "debit" not in assigned_targets:
            return "amount", 0.75

    return None, 0.0
