"""Reviewer-protected follow-up management."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.calling_eligibility import require_reviewer
from app.core.config import get_settings
from app.models.call_history import (
    FollowUpCreate, FollowUpPage, FollowUpRecord, FollowUpStatus, FollowUpUpdate,
)
from app.models.leads import LeadFileError
from app.services.call_dispatch import DispatchLedger
from app.services.follow_ups import FollowUpStore
from app.services.leads import LeadJsonService

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


def _lead_exists(lead_id: str) -> bool:
    try:
        return any(lead.lead_id == lead_id for lead in LeadJsonService(get_settings().lead_json_path).load())
    except LeadFileError:
        raise HTTPException(status_code=503, detail="Lead source is unavailable.") from None


def _record(row: dict) -> FollowUpRecord:
    return FollowUpRecord(**row)


@router.post("", response_model=FollowUpRecord, status_code=status.HTTP_201_CREATED)
def create_follow_up(payload: FollowUpCreate,
                     _: str = Depends(require_reviewer)) -> FollowUpRecord:
    if not _lead_exists(payload.lead_id):
        raise HTTPException(status_code=404, detail="Lead was not found.")
    if payload.scheduled_at.tzinfo is None or payload.scheduled_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="scheduled_at must include a timezone.")
    if payload.related_call_id is not None:
        call = DispatchLedger(get_settings().eligibility_db_path).get_record(str(payload.related_call_id))
        if call is None or call["lead_id"] != payload.lead_id:
            raise HTTPException(status_code=422, detail="Related call record does not belong to this lead.")
    try:
        # The current bearer-token auth identifies a role, not a reviewer account.
        row, _created = FollowUpStore(get_settings().eligibility_db_path).create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    # Idempotent retries return the original item with success.
    return _record(row)


@router.get("", response_model=FollowUpPage, dependencies=[Depends(require_reviewer)])
def list_follow_ups(
    lead_id: str | None = Query(default=None, min_length=1, max_length=256),
    follow_up_status: FollowUpStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> FollowUpPage:
    if lead_id is not None and not _lead_exists(lead_id):
        raise HTTPException(status_code=404, detail="Lead was not found.")
    rows, total = FollowUpStore(get_settings().eligibility_db_path).list(
        lead_id=lead_id, status=follow_up_status, limit=limit, offset=offset)
    return FollowUpPage(total=total, limit=limit, offset=offset,
                        follow_ups=[_record(row) for row in rows])


@router.get("/{follow_up_id}", response_model=FollowUpRecord, dependencies=[Depends(require_reviewer)])
def get_follow_up(follow_up_id: UUID) -> FollowUpRecord:
    row = FollowUpStore(get_settings().eligibility_db_path).get(str(follow_up_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Follow-up was not found.")
    return _record(row)


@router.patch("/{follow_up_id}", response_model=FollowUpRecord,
              dependencies=[Depends(require_reviewer)])
def update_follow_up(follow_up_id: UUID, payload: FollowUpUpdate) -> FollowUpRecord:
    if payload.scheduled_at is not None and (payload.scheduled_at.tzinfo is None or
                                              payload.scheduled_at.utcoffset() is None):
        raise HTTPException(status_code=422, detail="scheduled_at must include a timezone.")
    try:
        row = FollowUpStore(get_settings().eligibility_db_path).update(str(follow_up_id), payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Follow-up was not found.")
    return _record(row)
