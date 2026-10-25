from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


EmailStatus = Literal["pending", "sending", "sent", "failed", "uncertain"]


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: str = Field(min_length=1, max_length=256)
    template: str | None = Field(default=None, max_length=20000)
    regenerate: bool = False
    research_if_missing: bool = False
    draft_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class EmailApprovalRequest(EmailRequest):
    review_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool = Field(strict=True)
    subject: str | None = Field(default=None, min_length=5, max_length=180)
    body: str | None = Field(default=None, min_length=80, max_length=12000)


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: str
    business_name: str
    recipient: str
    sender: str
    proposal_file: str
    draft_key: str = ""
    template: str = ""
    subject: str
    body: str
    review_id: str
    approved: bool = False


class EmailResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email_id: UUID
    lead_id: str
    review_id: str | None = None
    draft_key: str | None = None
    business_name: str | None = None
    recipient: str | None = None
    sender: str | None = None
    proposal_file: str | None = None
    status: EmailStatus
    created_at: datetime
    sent_at: datetime | None = None
    message_id: str | None = None
    error: str | None = None


_PUBLIC_EMAIL_ERRORS = {
    "lead_source_unavailable", "lead_not_found", "proposal_invalid", "proposal_not_found",
    "recipient_unavailable", "email_configuration_unavailable", "email_review_changed",
    "proposal_not_approved", "email_sending_disabled", "email_approval_changed",
    "email_provider_outcome_uncertain", "email_provider_rejected", "email_not_found",
    "email_business_name_invalid", "email_draft_invalid", "proposal_empty", "email_generation_failed",
}


class EmailHistoryItem(EmailResult):
    @field_serializer("error")
    def safe_error(self, value: str | None) -> str | None:
        return value if value is None or value in _PUBLIC_EMAIL_ERRORS else "email_error_details_unavailable"


class EmailHistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    emails: list[EmailHistoryItem]
