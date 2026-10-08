from typing import Optional, Dict, Any, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from app.services.ingestion_service import IngestionService
from app.schemas.ingestion import (
    FileUploadResponse,
    DetectFormatResponse,
    ColumnMappingSubmission,
    JobStatusResponse,
    ParseExecutionResponse
)
from app.schemas.transaction import CanonicalStatementPackage, CanonicalTransaction, ParseErrorDetail

router = APIRouter(prefix="/api/v1", tags=["Data Ingestion & Parse Engine"])


@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_statement(file: UploadFile = File(...)):
    """
    Stage 1: File Upload & Security Verification.
    Saves file, calculates SHA-256 hash, and initializes parsing job.
    """
    try:
        content = await file.read()
        res = IngestionService.create_upload_job(file.filename, content)
        return FileUploadResponse(
            **res,
            message="File uploaded and registered successfully."
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/parse-jobs/{job_id}/detect", response_model=DetectFormatResponse)
def detect_and_suggest_mappings(job_id: str):
    """
    Stages 2 - 4: Format detection, table extraction, and intelligent column mapping inference.
    """
    try:
        result = IngestionService.detect_and_suggest_mappings(job_id)
        return DetectFormatResponse(**result)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Format detection failed: {str(e)}")


@router.post("/parse-jobs/{job_id}/execute", response_model=ParseExecutionResponse)
def execute_pipeline(job_id: str, submission: Optional[ColumnMappingSubmission] = None):
    """
    Stages 5 - 7: Normalization, validation, persistence, and canonical package preparation.
    Accepts optional custom column mapping override if user modified mappings in UI.
    """
    try:
        custom_mappings = submission.mappings if submission else None
        account_number = submission.account_number if submission and submission.account_number else "DEFAULT_ACC"
        currency = submission.currency if submission else "INR"

        res = IngestionService.execute_pipeline(
            job_id=job_id,
            custom_mappings=custom_mappings,
            account_number=account_number,
            currency=currency
        )
        return ParseExecutionResponse(**res)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")


@router.get("/parse-jobs/{job_id}/status")
def get_job_status(job_id: str):
    """
    Returns live lifecycle status and counters for a given parsing job.
    """
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
    """
    Returns paginated list of canonical normalized transactions.
    """
    try:
        return IngestionService.get_transactions(job_id, limit=limit, offset=offset)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/parse-jobs/{job_id}/errors", response_model=List[Dict[str, Any]])
def get_errors(job_id: str):
    """
    Returns audit log of warnings and errors detected during parsing.
    """
    try:
        return IngestionService.get_errors(job_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@router.get("/parse-jobs/{job_id}/export/canonical-json", response_model=CanonicalStatementPackage)
def export_canonical_json(job_id: str):
    """
    Exports the finalized Canonical Statement Package contract ready for Part 2 Reconciliation Engine.
    """
    try:
        return IngestionService.export_canonical_statement_package(job_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
