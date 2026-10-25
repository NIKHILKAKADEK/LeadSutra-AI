from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


FollowUpStatus = Literal["pending", "completed", "cancelled"]


class FollowUpCreate(BaseModel):
    lead_id: str = Field(min_length=1, max_length=256)
    scheduled_at: datetime
    notes: str | None = Field(default=None, max_length=2000)
    idempotency_key: UUID


class FollowUpUpdate(BaseModel):
    scheduled_at: datetime | None = None
    status: FollowUpStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class FollowUpItem(BaseModel):
    follow_up_id: UUID
    lead_id: str
    related_call_id: UUID | None
    scheduled_at: datetime
    status: FollowUpStatus
    assigned_reviewer: str | None
    notes: str | None
    idempotency_key: UUID
    created_at: datetime
    updated_at: datetime


class FollowUpPage(BaseModel):
    total: int
    limit: int
    offset: int
    follow_ups: list[FollowUpItem]
