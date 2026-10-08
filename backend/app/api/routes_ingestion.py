from typing import Optional, Dict, Any, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from app.services.ingestion_service import IngestionService
from app.schemas.ingestion import (
    CompanyCreate,
    CompanyResponse,
    ReconciliationCreate,
    ReconciliationResponse,
    SourceCreate,
    SourceResponse,
    FileUploadResponse,
    DetectFormatResponse,
    ColumnMappingSubmission,
    ParseExecutionResponse
)
from app.schemas.transaction import CanonicalStatementPackage

router = APIRouter(prefix="/api/v1", tags=["Data Ingestion & Parse Engine"])


# -------------------------------------------------------------
# Company Management (Section 5)
# -------------------------------------------------------------
@router.post("/companies", response_model=CompanyResponse)
def create_company(comp: CompanyCreate):
    try:
        return IngestionService.create_company(comp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies", response_model=List[CompanyResponse])
def get_companies():
    return IngestionService.get_companies()


@router.get("/companies/{company_id}", response_model=CompanyResponse)
def get_company(company_id: str):
    try:
        return IngestionService.get_company(company_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


# -------------------------------------------------------------
# Reconciliation & Financial Sources Context (Sections 6 & 7)
# -------------------------------------------------------------
@router.post("/reconciliations", response_model=ReconciliationResponse)
def create_reconciliation(rec: ReconciliationCreate):
    try:
        return IngestionService.create_reconciliation(rec)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reconciliations/{rec_id}", response_model=ReconciliationResponse)
def get_reconciliation(rec_id: str):
    try:
        return IngestionService.get_reconciliation(rec_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/reconciliations", response_model=List[ReconciliationResponse])
def get_reconciliations(company_id: Optional[str] = None):
    return IngestionService.get_reconciliations(company_id)


@router.post("/sources", response_model=SourceResponse)
def create_source(src: SourceCreate):
    try:
        return IngestionService.create_source(src)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources", response_model=List[SourceResponse])
def get_sources(reconciliation_id: str = Query(...)):
    return IngestionService.get_sources(reconciliation_id)


# -------------------------------------------------------------
# File Ingestion & Detection Endpoints (Sections 11 & 12)
# -------------------------------------------------------------
@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    reconciliation_id: Optional[str] = Form(default="REC_DEMO_01"),
    source_id: Optional[str] = Form(default="SRC_DEMO_BANK"),
    source_type: Optional[str] = Form(default="BANK_STATEMENT")
):
    try:
        content = await file.read()
        res = IngestionService.create_upload_job(
            filename=file.filename,
            file_bytes=content,
            reconciliation_id=reconciliation_id,
            source_id=source_id,
            source_type=source_type
        )
        msg = "File uploaded and registered successfully."
        if res.get("is_duplicate"):
            msg = "Warning: Duplicate file detected via SHA-256 fingerprint within this reconciliation."
        return FileUploadResponse(**res, message=msg)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/files/detect", response_model=DetectFormatResponse)
def detect_file_alias(job_id: str = Query(...)):
    try:
        result = IngestionService.detect_and_suggest_mappings(job_id)
        return DetectFormatResponse(**result)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parse-jobs/{job_id}/detect", response_model=DetectFormatResponse)
def detect_and_suggest_mappings(job_id: str):
    try:
        result = IngestionService.detect_and_suggest_mappings(job_id)
        return DetectFormatResponse(**result)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Format detection failed: {str(e)}")


# -------------------------------------------------------------
# Execution, Mapping, & Retry Endpoints (Sections 15, 16, 26)
# -------------------------------------------------------------
@router.post("/files/parse", response_model=ParseExecutionResponse)
def parse_file_alias(job_id: str = Query(...), submission: Optional[ColumnMappingSubmission] = None):
    return execute_pipeline(job_id, submission)


@router.post("/parse-jobs/{job_id}/execute", response_model=ParseExecutionResponse)
@router.post("/parse-jobs/{job_id}/mapping", response_model=ParseExecutionResponse)
def execute_pipeline(job_id: str, submission: Optional[ColumnMappingSubmission] = None):
    try:
        custom_mappings = submission.mappings if submission else None
        account_number = submission.account_number if submission and submission.account_number else "DEFAULT_ACC"
        currency = submission.currency if submission else "INR"
        source_type = submission.source_type if submission else "BANK_STATEMENT"
        remember = submission.remember_rules if submission else True

        res = IngestionService.execute_pipeline(
            job_id=job_id,
            custom_mappings=custom_mappings,
            account_number=account_number,
            currency=currency,
            source_type=source_type,
            remember_rules=remember
        )
        return ParseExecutionResponse(**res)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")


@router.post("/parse-jobs/{job_id}/retry", response_model=DetectFormatResponse)
def retry_job(job_id: str):
    try:
        res = IngestionService.retry_job(job_id)
        return DetectFormatResponse(**res)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


# -------------------------------------------------------------
# Query, Status, & Export Endpoints (Sections 20 & 27)
# -------------------------------------------------------------
@router.get("/parse-jobs/{job_id}")
@router.get("/parse-jobs/{job_id}/status")
def get_job_status(job_id: str):
    try:
        return IngestionService.get_job_status(job_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/parse-jobs/{job_id}/transactions", response_model=List[Dict[str, Any]])
def get_transactions(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0)
):
    try:
        return IngestionService.get_transactions(job_id, limit=limit, offset=offset)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/parse-jobs/{job_id}/errors", response_model=List[Dict[str, Any]])
def get_errors(job_id: str):
    try:
        return IngestionService.get_errors(job_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/parse-jobs/{job_id}/export/canonical-json", response_model=CanonicalStatementPackage)
def export_canonical_json(job_id: str):
    try:
        return IngestionService.export_canonical_statement_package(job_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
