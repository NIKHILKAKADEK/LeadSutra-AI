"""Schemas for protected outbound dispatch requests and results."""
from enum import StrEnum
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DispatchStatus(StrEnum):
    blocked = "blocked"
    dry_run = "dry_run"
    dispatching = "dispatching"
    dispatched = "dispatched"
    duplicate = "duplicate"
    provider_error = "provider_error"
    uncertain = "uncertain"


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str = Field(min_length=1, max_length=256)
    phone_number: str = Field(min_length=1, max_length=64)
    idempotency_key: UUID


class LeadCallContext(BaseModel):
    """Minimal facts sourced from the validated lead record."""

    lead_business_name: str | None = None
    verified_lead_name: str | None = None

    @field_validator("lead_business_name", "verified_lead_name", mode="before")
    @classmethod
    def blank_strings_are_missing(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value


class RepresentedBusinessContext(BaseModel):
    """Caller identity, present only when explicitly configured as verified."""

    verified_business_name: str = Field(min_length=1, max_length=256)

    @field_validator("verified_business_name")
    @classmethod
    def trim_business_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A verified represented-business name is required.")
        return value


class OutboundCallContext(BaseModel):
    """Validated per-call values; static agent instructions are kept separately."""

    lead: LeadCallContext
    represented_business: RepresentedBusinessContext
    contact_basis_status: Literal["verified"]

    def to_provider_context(self, allowed_variables: set[str]) -> dict[str, str]:
        """Flatten only template-declared dynamic variables for SDK call_context."""
        values = {
            "lead_business_name": self.lead.lead_business_name,
            "verified_lead_name": self.lead.verified_lead_name,
            "verified_business_name": self.represented_business.verified_business_name,
            "contact_basis_status": self.contact_basis_status,
        }
        return {key: value for key, value in values.items()
                if value is not None and key in allowed_variables}


class DispatchResult(BaseModel):
    status: DispatchStatus
    eligible: bool
    dispatched: bool = False
    dispatch_enabled: bool
    lead_id: str
    normalized_phone_number: str | None = None
    agent_id: int | None = None
    reason_codes: list[str] = Field(default_factory=list)
    provider_request_id: str | None = None
