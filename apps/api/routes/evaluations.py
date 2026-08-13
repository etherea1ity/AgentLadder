"""Read-only evaluation summary API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from klara.eval.catalog import load_evaluation_summary


router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.get("/summary")
def get_evaluation_summary():
    """Return aggregate report fields without hidden cases or review identities."""

    try:
        return load_evaluation_summary()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="evaluation_report_invalid") from exc
