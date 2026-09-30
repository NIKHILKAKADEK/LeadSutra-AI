"""LeadSutra business profile model."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class BusinessProfile(BaseModel):
    """Structured Business Profile representation extracted for a BusinessLead.

    Used downstream for Lead Scoring, Proposal Generation, AI Qualification, and Outreach.
    """

    lead_id: str | None = Field(
        default=None,
        description="Unique identifier linking to the parent BusinessLead.",
    )
    external_place_id: str | None = Field(
        default=None,
        description="Provider-agnostic place identifier from the discovery source.",
    )
    source: str = Field(
        default="google",
        description="Discovery source provider ('google' or 'foursquare').",
    )
    business_name: str = Field(
        ...,
        description="Official name of the business.",
    )
    category: str | None = Field(
        default=None,
        description="Primary business category from provider discovery.",
    )
    sub_category: str | None = Field(
        default=None,
        description="More specific sub-category or industry specialization extracted from website.",
    )
    description: str | None = Field(
        default=None,
        description="Extracted business description.",
    )
    services: list[str] = Field(
        default_factory=list,
        description="List of services explicitly offered by the business.",
    )
    products: list[str] = Field(
        default_factory=list,
        description="List of products explicitly offered by the business.",
    )
    target_customers: list[str] = Field(
        default_factory=list,
        description="Explicit target customer demographics or audience segments.",
    )
    about_info: str | None = Field(
        default=None,
        description="About/Company introductory details, positioning, and areas served.",
    )
    address: str | None = Field(
        default=None,
        description="Formatted physical address.",
    )
    phone: str | None = Field(
        default=None,
        description="Contact phone number.",
    )
    email: str | None = Field(
        default=None,
        description="Contact email address.",
    )
    website: str | None = Field(
        default=None,
        description="Official website URL.",
    )
    social_links: dict[str, str] = Field(
        default_factory=dict,
        description="Social media profile URLs (instagram, facebook, linkedin, twitter, youtube).",
    )
    operating_hours: str | dict[str, Any] | None = Field(
        default=None,
        description="Operating hours of the business.",
    )
    online_presence: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of online & social media presence.",
    )
    profile_extraction_status: str = Field(
        default="success",
        description="Profile extraction status ('success', 'partial', 'skipped', 'failed').",
    )
    extraction_source: str = Field(
        default="hybrid",
        description="Data origin for profile ('hybrid', 'provider_only', 'website_enriched').",
    )

    def to_dict(self) -> dict[str, Any]:
        """Return profile attributes as a dictionary."""
        return self.model_dump()
