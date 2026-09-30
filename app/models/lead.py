"""LeadSutra common business lead model."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class BusinessLead(BaseModel):
    """Common LeadSutra representation of a discovered business lead.
    
    This provider-agnostic model normalizes attributes across discovery services
    (e.g., Google Places, Foursquare).
    """

    external_place_id: str | None = Field(
        default=None,
        description="Provider-agnostic place identifier from the discovery source.",
    )
    source: str = Field(
        default="google",
        description="The source provider of this lead (e.g., 'google', 'foursquare').",
    )
    name: str = Field(
        ...,
        description="Official name of the business.",
    )
    category: str | None = Field(
        default=None,
        description="Primary business category or industry type.",
    )
    rating: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
        description="Business rating on a normalized 0.0 - 5.0 scale.",
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
    address: str | None = Field(
        default=None,
        description="Formatted physical address of the business.",
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Geographic latitude coordinate.",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Geographic longitude coordinate.",
    )
    description: str | None = Field(
        default=None,
        description="Business description scraped from website or about page.",
    )
    social_links: dict[str, str] = Field(
        default_factory=dict,
        description="Social media links extracted from website (e.g. instagram, facebook, linkedin, twitter, youtube).",
    )
    services: list[str] = Field(
        default_factory=list,
        description="Business services or sub-categories scraped from website.",
    )
    website_status: str | None = Field(
        default=None,
        description="Website status ('accessible', 'inaccessible', 'invalid_url', 'timeout', 'blocked', 'no_website').",
    )
    scrape_status: str | None = Field(
        default=None,
        description="Scraping status ('success', 'failed', 'timeout', 'blocked', 'skipped', 'no_website').",
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw metadata and scraped website details.",
    )
    contact_person: str | None = Field(
        default=None,
        description="Extracted contact person's name (e.g. founder, manager, key contact).",
    )
    contact_emails: list[str] = Field(
        default_factory=list,
        description="All validated public contact emails discovered for this business.",
    )
    contact_page_url: str | None = Field(
        default=None,
        description="URL of the business contact page.",
    )
    about_page_url: str | None = Field(
        default=None,
        description="URL of the business about/company page.",
    )
    operating_hours: str | dict[str, Any] | None = Field(
        default=None,
        description="Operating hours of the business.",
    )
    extraction_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata recording field provenance, extraction source, and confidence.",
    )
    contact_extraction_status: str = Field(
        default="skipped",
        description="Contact extraction status ('success', 'skipped', 'failed', 'no_website').",
    )
    lead_score: int | None = Field(
        default=None,
        description="Numerical lead score on 0-100 scale.",
    )
    priority: str | None = Field(
        default=None,
        description="Lead priority ('high', 'medium', 'low').",
    )
    qualification_status: str | None = Field(
        default=None,
        description="Qualification status ('qualified', 'partially_qualified', 'unqualified').",
    )
    score_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Detailed score breakdown across the 6 scoring parameters.",
    )

    def to_dict(self) -> dict[str, Any]:
        """Return lead attributes as a dictionary."""
        return self.model_dump()


class BusinessSearchResponse(BaseModel):
    """Structured response container including lead results and provider metadata."""

    provider: str = Field(
        ...,
        description="The discovery provider that fulfilled the search ('google' or 'foursquare').",
    )
    fallback_used: bool = Field(
        default=False,
        description="True if automatic fallback to secondary provider occurred, False otherwise.",
    )
    leads: list[BusinessLead] = Field(
        default_factory=list,
        description="List of normalized business leads returned by the provider.",
    )

    def to_dict(self) -> dict[str, Any]:
        """Return response attributes as a dictionary."""
        return self.model_dump()

