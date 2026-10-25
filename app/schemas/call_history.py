"""Protected projections for dispatch history."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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