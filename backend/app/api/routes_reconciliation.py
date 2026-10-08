from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query
from app.services.reconciliation_service import ReconciliationService
from app.schemas.reconciliation import (
    HumanReviewSubmission,
    ReconciliationSummaryReport,
    MatchResultItem,
    AnomalyItem
)

router = APIRouter(prefix="/api/v1", tags=["Process 02: Reconciliation & Anomaly Engine"])


@router.get("/reconciliations/{rec_id}/input-status")
def get_reconciliation_input_status(rec_id: str):
    """
    Checks if Bank Statement and Company Ledger inputs are ready (Section 37 Screen 1).
    """
    try:
        return ReconciliationService.get_input_status(rec_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reconciliations/{rec_id}/seed-demo")
def seed_demo_transactions(rec_id: str):
    """
    Seeds comprehensive test transactions for both Bank Statement and Company Ledger.
    """
    try:
        return ReconciliationService.seed_demo_transactions(rec_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reconciliations/{rec_id}/start")
def start_reconciliation(
    rec_id: str,
    bank_source_id: Optional[str] = Query(default=None),
    company_source_id: Optional[str] = Query(default=None)
):
    """
    Starts Process 02: Staged matching, anomaly detection, and AI forensic investigation.
    """
    try:
        return ReconciliationService.start_reconciliation(
            reconciliation_id=rec_id,
            bank_source_id=bank_source_id,
            company_source_id=company_source_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconciliation run failed: {str(e)}")


@router.get("/reconciliations/{rec_id}/results", response_model=ReconciliationSummaryReport)
def get_reconciliation_results(rec_id: str):
    """
    Returns the comprehensive reconciliation summary and balance reports (Section 28).
    """
    try:
        return ReconciliationService.get_reconciliation_summary(rec_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reconciliations/{rec_id}/matches", response_model=List[Dict[str, Any]])
def get_matches(rec_id: str, status: Optional[str] = Query(default=None)):
    """
    Returns list of matches (MATCHED, PROBABLE_MATCH, UNMATCHED).
    """
    try:
        return ReconciliationService.get_matches(rec_id, status_filter=status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reconciliations/{rec_id}/anomalies", response_model=List[Dict[str, Any]])
def get_anomalies(rec_id: str, severity: Optional[str] = Query(default=None)):
    """
    Returns list of financial anomalies with forensic AI investigation findings.
    """
    try:
        return ReconciliationService.get_anomalies(rec_id, severity_filter=severity)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomalies/{anomaly_id}/review")
def review_anomaly(anomaly_id: str, review: HumanReviewSubmission):
    """
    Human Review Action (Section 29):
    Confirm Match, Mark Unmatched, or Mark Duplicate.
    """
    try:
        return ReconciliationService.review_anomaly(anomaly_id, review)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/matches/{match_id}/confirm")
def confirm_match(match_id: str):
    """
    Confirms a probable match as exact verified match.
    """
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE matches SET status = 'MATCHED', confidence = 1.0 WHERE id = ?", (match_id,))
        conn.close()
        return {"match_id": match_id, "status": "MATCHED", "message": "Match manually confirmed."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/matches/{match_id}/reject")
def reject_match(match_id: str):
    """
    Rejects a candidate match and marks it as UNMATCHED.
    """
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE matches SET status = 'UNMATCHED', confidence = 0.0 WHERE id = ?", (match_id,))
        conn.close()
        return {"match_id": match_id, "status": "UNMATCHED", "message": "Match manually rejected."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
