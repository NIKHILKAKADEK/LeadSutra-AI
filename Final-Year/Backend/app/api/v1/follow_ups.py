from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user
from app.schemas.follow_ups import FollowUpCreate, FollowUpItem, FollowUpPage, FollowUpStatus, FollowUpUpdate
from app.services.follow_ups import FollowUpStore

router = APIRouter(prefix="/follow-ups", tags=["Follow-ups"])


@router.get("", response_model=FollowUpPage, dependencies=[Depends(get_current_user)])
def list_follow_ups(
    status_filter: FollowUpStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> FollowUpPage:
    rows, total = FollowUpStore().list(status=status_filter, limit=limit, offset=offset)
    return FollowUpPage(total=total, limit=limit, offset=offset, follow_ups=rows)


@router.post("", response_model=FollowUpItem, status_code=status.HTTP_201_CREATED)
def create_follow_up(payload: FollowUpCreate, user: dict = Depends(get_current_user)) -> FollowUpItem:
    try:
        row = FollowUpStore().create(payload, user.get("email", "unknown"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return FollowUpItem(**row)


@router.patch("/{follow_up_id}", response_model=FollowUpItem, dependencies=[Depends(get_current_user)])
def update_follow_up(follow_up_id: UUID, payload: FollowUpUpdate) -> FollowUpItem:
    row = FollowUpStore().update(follow_up_id, payload)
    if row is None:
        raise HTTPException(status_code=404, detail="Follow-up was not found.")
    return FollowUpItem(**row)
