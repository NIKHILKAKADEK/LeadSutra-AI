from datetime import datetime

from pydantic import BaseModel


class AnalyticsLead(BaseModel):
    lead_id: str
    business_name: str
    category: str | None
    lead_score: float | None
    priority: str
    updated_at: datetime | None


class AnalyticsActivity(BaseModel):
    id: str
    label: str
    status: str
    created_at: datetime | None


class AnalyticsOverview(BaseModel):
    generated_at: datetime
    leads_total: int
    high_priority_leads: int
    qualified_leads: int
    websites_total: int
    emails_total: int
    emails_sent: int
    calls_total: int
    calls_dispatched: int
    recent_leads: list[AnalyticsLead]
    recent_emails: list[AnalyticsActivity]
    recent_calls: list[AnalyticsActivity]
