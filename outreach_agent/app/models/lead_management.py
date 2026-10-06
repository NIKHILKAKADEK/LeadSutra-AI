"""Frontend-safe projections of leads loaded from the configured JSON source."""
from pydantic import BaseModel, Field


class LeadListItem(BaseModel):
    lead_id: str
    business_name: str | None
    category: str | None
    qualification_status: str | None
    lead_score: float | None
    phone_numbers: list[str]


class LeadListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    leads: list[LeadListItem]


class LeadDetailsResponse(BaseModel):
    lead_id: str
    business_name: str | None
    website: str | None
    category: str | None
    address: str | None
    contact_names: list[str] = Field(default_factory=list)
    phone_numbers: list[str]
    lead_score: float | None
    qualification_status: str | None
