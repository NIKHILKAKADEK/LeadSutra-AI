"""Protected outbound call history and dispatch endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.api.v1.calling_eligibility import require_admin, require_reviewer
from app.schemas.call_dispatch import (
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
)
from app.schemas.call_history import CallHistoryItem, CallHistoryPage
from app.services.outreach_repository import DispatchLedger
from app.services.voice_service import dispatch_voice_call

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get(
    "",
    response_model=CallHistoryPage,
    dependencies=[Depends(require_reviewer)],
)
def list_call_history(
    lead_id: str | None = Query(default=None, min_length=1, max_length=256),
    dispatch_status: DispatchStatus | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> CallHistoryPage:
    records, total = DispatchLedger(
        get_settings().eligibility_db_path
    ).list_records(
        lead_id=lead_id,
        status=dispatch_status.value if dispatch_status else None,
        limit=limit,
        offset=offset,
    )

    return CallHistoryPage(
        total=total,
        limit=limit,
        offset=offset,
        calls=records,
    )


@router.get(
    "/{call_id}",
    response_model=CallHistoryItem,
    dependencies=[Depends(require_reviewer)],
)
def get_call_history(call_id: UUID) -> CallHistoryItem:
    record = DispatchLedger(
        get_settings().eligibility_db_path
    ).get_record(str(call_id))

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Call record was not found.",
        )

    return CallHistoryItem(**record)


@router.post(
    "/dispatch",
    response_model=DispatchResult,
    dependencies=[Depends(require_admin)],
)
def dispatch_outbound_call(request: DispatchRequest) -> DispatchResult:
    """Dry-run by default; dispatch requires explicit server-side enablement."""
    return dispatch_voice_call(request)