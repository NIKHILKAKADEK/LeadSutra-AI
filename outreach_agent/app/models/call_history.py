"""Protected projections for dispatch history and follow-up management."""
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CallHistoryItem(BaseModel):
    call_id: UUID
    lead_id: str
    phone_number: str
    dispatch_status: str
    provider_request_id: str | None
    dispatch_requested: bool
    provider_accepted: bool
    call_outcome: str = "unknown"
    created_at: datetime
    updated_at: datetime


class CallHistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    calls: list[CallHistoryItem]


class FollowUpStatus(StrEnum):
    pending = "pending"
    completed = "completed"
    cancelled = "cancelled"


class FollowUpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str = Field(min_length=1, max_length=256)
    related_call_id: UUID | None = None
    scheduled_at: datetime
    notes: str | None = Field(default=None, max_length=4000)
    idempotency_key: UUID


class FollowUpUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime | None = None
    status: FollowUpStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)


class FollowUpRecord(BaseModel):
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
    follow_ups: list[FollowUpRecord]
