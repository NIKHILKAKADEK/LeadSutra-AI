"""Request and response models for outbound calling eligibility."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConsentStatus(StrEnum):
    verified = "verified"
    unknown = "unknown"
    denied = "denied"
    revoked = "revoked"
    pending_verification = "pending_verification"


class SuppressionStatus(StrEnum):
    suppressed = "suppressed"
    not_suppressed = "not_suppressed"
    unknown = "unknown"


class CheckStatus(StrEnum):
    approved = "approved"
    denied = "denied"
    unknown = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConsentRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str = Field(min_length=1, max_length=256)
    phone_number: str = Field(min_length=1, max_length=64)
    consent_status: ConsentStatus = ConsentStatus.unknown
    consent_scope: str | None = Field(default=None, max_length=512)
    consent_source: str | None = Field(default=None, max_length=512)
    evidence_reference: str | None = Field(default=None, max_length=2048)
    recorded_at: datetime = Field(default_factory=utc_now)
    verified_at: datetime | None = None
    verified_by: str | None = Field(default=None, max_length=256)
    expiry_at: datetime | None = None
    revoked_at: datetime | None = None

    @field_validator("recorded_at", "verified_at", "expiry_at", "revoked_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Timestamps must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_verified_evidence(self) -> "ConsentRecordInput":
        if self.consent_status == ConsentStatus.verified and not all(
            (self.consent_scope, self.consent_source, self.evidence_reference)
        ):
            raise ValueError("Verified consent requires scope, source, and evidence reference.")
        if self.consent_status == ConsentStatus.revoked and self.revoked_at is None:
            raise ValueError("Revoked consent requires revoked_at.")
        return self


class ConsentStatusResponse(BaseModel):
    lead_id: str
    phone_number: str
    consent_status: ConsentStatus
    consent_scope: str | None
    consent_source: str | None
    recorded_at: datetime | None
    verified_at: datetime | None
    verified_by: str | None
    expiry_at: datetime | None
    revoked_at: datetime | None


class SuppressionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(min_length=1, max_length=64)
    suppression_status: SuppressionStatus = SuppressionStatus.suppressed
    reason: str | None = Field(default=None, max_length=512)


class SuppressionResponse(BaseModel):
    phone_number: str
    suppression_status: SuppressionStatus
    reason: str | None
    updated_at: datetime | None


class TelecomComplianceInput(BaseModel):
    """Externally attested checks; the application does not query DND itself."""

    preference_status: CheckStatus = CheckStatus.unknown
    route_status: CheckStatus = CheckStatus.unknown
    provider_reference: str | None = Field(default=None, max_length=512)


class EligibilityResponse(BaseModel):
    eligible: bool
    reason_codes: list[str]
    checked_at: datetime
    lead_id: str
    normalized_phone_number: str | None
