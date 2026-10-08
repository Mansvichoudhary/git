# FinAgent — Automated Bank Statement Reconciliation & Anomaly Investigation Agent

## Part 1: Data Ingestion & Parse Engine

### Overview
Part 1 converts messy, unstructured, multi-bank financial statements (CSV, XLSX, PDF) into clean, deterministic, standardized canonical transaction records ready for Part 2 (Reconciliation & Anomaly Engine).

---

### Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

2. **Launch Application**:
   ```bash
   python run.py
   ```
   - **Interactive Web UI**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
   - **Swagger REST API**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

3. **Run Automated Test Suite**:
   ```bash
   python backend/tests/test_ingestion.py
   ```

---

### Pipeline Architecture (7 Stages)

1. **File Upload & Verification**: Multi-bank file validation, SHA-256 hash calculation, size checks.
2. **File Format Detection**: Magic byte sniffing (CSV, XLSX, PDF text vs OCR).
3. **Raw Data Extraction**: Smart header offset sniffing (skips bank branch/customer address noise).
4. **Intelligent Schema Mapping**: 3-tier cascade (Exact alias -> RapidFuzz similarity -> Heuristic patterns) with interactive manual override.
5. **Deterministic Normalization**: Multi-bank dates to ISO `YYYY-MM-DD`, Indian currency strings (`₹1,50,000.00`) to exact Decimals, Debit/Credit resolution.
6. **Strict Business Validation & Error Queue**: Auditable categorization into `WARNING`, `ERROR`, and `FATAL`. Zero silent data loss.
7. **Canonical Transaction Packaging**: Generates deterministic `TXN_<HASH>` IDs and exports standard Canonical JSON.

---

### Specifications & God Prompt
- Full Technical Architecture: [`FinAgent_Data_Ingestion_Parse_Engine.md`](file:///c:/Users/ANJALI/OneDrive/Desktop/git/FinAgent_Data_Ingestion_Parse_Engine.md)
- AntiGravity God Prompt: [`ANTIGRAVITY_GOD_PROMPT.md`](file:///c:/Users/ANJALI/OneDrive/Desktop/git/ANTIGRAVITY_GOD_PROMPT.md)
