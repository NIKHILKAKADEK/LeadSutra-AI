"""Shared discovery, enrichment, scoring and API contracts."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from app.core.config import DiscoverySettings


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )


class ContactsSection(StrictOutputModel):
    contact_person: str | None = None
    emails: list[str] = Field(
        default_factory=list
    )
    phone_numbers: list[str] = Field(
        default_factory=list
    )


class SocialLinksSection(StrictOutputModel):
    facebook: HttpUrl | None = None
    instagram: HttpUrl | None = None
    linkedin: HttpUrl | None = None


class ScoringSection(StrictOutputModel):
    lead_score: float | None = None
    priority: str = "Unknown"
    qualification_status: str = "Unknown"
    score_breakdown: dict[str, Any] = Field(default_factory=dict)


class WebsiteStatus(str, Enum):
    ACTIVE = "active"
    UNREACHABLE = "unreachable"
    BLOCKED = "blocked"
    INVALID_URL = "invalid_url"
    NOT_FOUND = "not_found"
    UNCERTAIN = "uncertain"


class CrawlError(BaseModel):
    url: str | None = None
    message: str


class WebsiteLink(BaseModel):
    url: str
    text: str | None = None


class WebsitePage(BaseModel):
    page_url: str
    page_title: str | None = None
    meta_description: str | None = None
    main_text: str = ""
    contact_text: str = ""
    page_type: str = "other"
    extraction_status: str = "success"
    # Evidence captured during crawling.
    outgoing_links: list[WebsiteLink] = Field(
        default_factory=list
    )
    technology_signals: list[str] = Field(
        default_factory=list
    )
    response_headers: dict[str, str] = Field(
        default_factory=dict
    )


class WebsiteCrawlResult(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )
    lead_id: str
    website_status: WebsiteStatus
    website_url: str | None = None
    website_content: list[WebsitePage] = Field(
        default_factory=list
    )
    about: list[dict[str, str]] = Field(
        default_factory=list
    )
    services: list[dict[str, str]] = Field(
        default_factory=list
    )
    contact_page_url: str | None = None
    pages_visited: list[str] = Field(
        default_factory=list
    )
    crawl_errors: list[CrawlError] = Field(
        default_factory=list
    )
    field_sources: dict[str, list[str]] = Field(
        default_factory=dict
    )


@dataclass(frozen=True)
class WebsiteCrawlerConfig:
    max_pages: int = 8
    timeout_seconds: float = 15.0
    min_text_for_static: int = 180
    user_agent: str = (
        "LeadSutraResearchBot/1.0 "
        "(+website content discovery)"
    )
    concurrency: int = 3
    crawl_timeout_seconds: float = 40.0
    max_response_bytes: int = 2_000_000
    def __post_init__(self) -> None:
        if self.max_pages < 1:
            raise ValueError(
                "max_pages must be at least 1"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )
        if (
            self.concurrency < 1
            or self.crawl_timeout_seconds <= 0
            or self.max_response_bytes < 1
        ):
            raise ValueError(
                "concurrency, crawl timeout, "
                "and response limit must be positive"
            )


class ProfileFact(BaseModel):
    """
    A normalized fact plus the exact page(s) supporting it.
    """
    value: str
    source_urls: list[str] = Field(
        min_length=1
    )


class OperatingHours(BaseModel):
    day: str
    opens: str | None = None
    closes: str | None = None
    closed: bool = False
    source_url: str


class BusinessProfile(BaseModel):
    """
    Evidence-backed profile kept separate from BusinessRecord.
    """
    lead_id: str
    business_name: str
    services: list[ProfileFact] = Field(
        default_factory=list
    )
    products: list[ProfileFact] = Field(
        default_factory=list
    )
    target_customers: list[ProfileFact] = Field(
        default_factory=list
    )
    about_info: list[ProfileFact] = Field(
        default_factory=list
    )
    business_description: ProfileFact | None = None
    operating_hours: list[OperatingHours] = Field(
        default_factory=list
    )
    field_sources: dict[str, list[str]] = Field(
        default_factory=dict
    )


class ContactValue(BaseModel):
    value: str
    source_urls: list[str] = Field(
        min_length=1
    )


class ContactEmail(BaseModel):
    email: str
    source_urls: list[str] = Field(
        min_length=1
    )


class ContactPhone(BaseModel):
    value: str
    normalized: str
    source_urls: list[str] = Field(
        min_length=1
    )


class ContactExtraction(BaseModel):
    lead_id: str
    contact_person: ContactValue | None = None
    contact_emails: list[ContactEmail] = Field(
        default_factory=list
    )
    phone_numbers: list[ContactPhone] = Field(
        default_factory=list
    )
    contact_page_url: str | None = None
    # Backward-compatible convenience fields.
    email: str | None = None
    phone: str | None = None
    field_sources: dict[str, list[str]] = Field(
        default_factory=dict
    )


class SocialAccount(BaseModel):
    url: str
    source_url: str


class SocialMediaExtraction(BaseModel):
    lead_id: str
    facebook: SocialAccount | None = None
    instagram: SocialAccount | None = None
    linkedin: SocialAccount | None = None
    twitter: SocialAccount | None = None
    field_sources: dict[str, list[str]]


class DetectedTechnology(BaseModel):
    name: str
    evidence: list[str] = Field(
        min_length=1
    )
    source_urls: list[str] = Field(
        min_length=1
    )


class TechnologyExtraction(BaseModel):
    lead_id: str
    technologies: list[DetectedTechnology] = Field(
        default_factory=list
    )
    field_sources: dict[str, list[str]] = Field(
        default_factory=dict
    )




class BusinessRecord(BaseModel):
    """
    Verified, basic business listing data returned by discovery.
    """
    model_config = ConfigDict(
        extra="ignore"
    )
    lead_id: str
    place_id: str | None = None
    primary_type: str | None = None
    discovery_source: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    source_attributions: list[dict[str, Any]] = Field(
        default_factory=list
    )
    business_name: str
    category: str | None = None
    sub_category: str | None = None
    description: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = None
    source_url: str | None = None
    source_ref: str | None = None
    # ------------------------------------------------------------------
    # VALIDATORS
    # ------------------------------------------------------------------
    @field_validator("business_name")
    @classmethod
    def name_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(
                "business_name must not be empty"
            )
        return value
    @field_validator("email")
    @classmethod
    def valid_email_only(
        cls,
        value: str | None,
    ) -> str | None:
        """
        Reject URLs and malformed values in the email slot.
        """
        if value is None:
            return None
        value = value.strip()
        if (
            not value
            or "://" in value
            or value.casefold().startswith("www.")
            or not re.fullmatch(
                r"[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+",
                value,
            )
        ):
            return None
        return value.casefold()
    @field_validator("rating")
    @classmethod
    def valid_rating(
        cls,
        value: float | None,
    ) -> float | None:
        if value is not None and not 0 <= value <= 5:
            raise ValueError(
                "rating must be between 0 and 5"
            )
        return value
    @field_validator("review_count")
    @classmethod
    def valid_review_count(
        cls,
        value: int | None,
    ) -> int | None:
        if value is not None and value < 0:
            raise ValueError(
                "review_count cannot be negative"
            )
        return value
    # ------------------------------------------------------------------
    # STABLE ID
    # ------------------------------------------------------------------
    @classmethod
    def stable_id(
        cls,
        source_url: str | None,
        name: str,
        address: str | None,
        place_id: str | None = None,
    ) -> str:
        """
        Derive a repeatable ID from:
        1. Google Places place_id when available
        2. source URL
        3. business name + address
        """
        identity = (
            f"places:{place_id}"
            if place_id
            else source_url
        ) or json.dumps(
            [
                name.casefold().strip(),
                (address or "").casefold().strip(),
            ]
        )
        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()[:24]
    # ------------------------------------------------------------------
    # SAFE CONSTRUCTION
    # ------------------------------------------------------------------
    @classmethod
    def from_extracted(
        cls,
        data: dict[str, Any],
    ) -> "BusinessRecord":
        """
        Create a BusinessRecord from scraper/provider data.
        If lead_id is missing, generate the same stable ID
        used by the original scraper.
        """
        values = dict(data)
        values.setdefault(
            "lead_id",
            cls.stable_id(
                values.get("source_url"),
                values.get("business_name", ""),
                values.get("address"),
                values.get("place_id"),
            ),
        )
        return cls.model_validate(values)


class LeadDiscoveryRequest(StrictOutputModel):
    query: str = Field(min_length=1)
    location: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=60)
    priority: Literal["high", "mid", "low"] = Field(
        description="Existing priority band; mid maps to the scorer's Medium label.",
    )


class DiscoveryData(BusinessRecord):
    # The existing business fields/validators are reused; the ID lives at the root.
    lead_id: str | None = Field(default=None, exclude=True)
    # Scoring fallback and provenance remain internal, like provider metadata.
    sub_category: str | None = Field(default=None, exclude=True)
    source_ref: str | None = Field(default=None, exclude=True)
    # Provider metadata remains internal and is omitted from public lead artifacts.
    place_id: str | None = Field(default=None, exclude=True)
    primary_type: str | None = Field(default=None, exclude=True)
    discovery_source: str | None = Field(default=None, exclude=True)
    fallback_used: bool = Field(default=False, exclude=True)
    fallback_reason: str | None = Field(default=None, exclude=True)
    source_attributions: list[dict[str, Any]] = Field(default_factory=list, exclude=True)


class EnrichmentSocialLinks(SocialLinksSection):
    twitter: HttpUrl | None = None


class EnrichmentData(ContactsSection):
    website_status: str = "not_checked"
    website_url: str | None = None
    about: str = ""
    business_description: str | None = None
    services: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    target_customers: list[str] = Field(default_factory=list)
    social_links: EnrichmentSocialLinks = Field(default_factory=EnrichmentSocialLinks)
    technology_stack: list[str] = Field(default_factory=list)
    contact_page_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def omit_retired_fields(cls, value: Any) -> Any:
        """Read older saved runs without restoring retired public fields."""
        if isinstance(value, dict):
            return {key: item for key, item in value.items()
                    if key not in {"final_url", "operating_hours"}}
        return value


class ScoringData(ScoringSection):
    score_breakdown: dict[str, Any] = Field(default_factory=dict, exclude=True)


class LeadResult(StrictOutputModel):
    lead_id: str
    discovery: DiscoveryData
    enrichment: EnrichmentData
    scoring: ScoringData


class LeadDiscoveryResponse(StrictOutputModel):
    success: bool
    query: str
    location: str
    count: int
    source: str
    fallback_used: bool
    leads: list[LeadResult]


class StoredLeadPage(StrictOutputModel):
    total: int
    limit: int
    offset: int
    items: list[LeadResult]


DiscoverRequest = LeadDiscoveryRequest


DiscoverResponse = LeadDiscoveryResponse


DiscoverySection = DiscoveryData


EnrichmentSection = EnrichmentData


DiscoveryScoringSection = ScoringData


CanonicalLead = LeadResult


@dataclass(frozen=True)
class ScoringConfig:
    """Central, tunable rule thresholds. No model-generated judgments are used."""
    minimum_evidence_coverage: float = 60.0
    high_priority_minimum: float = 80.0
    medium_priority_minimum: float = 60.0
    needs_review_minimum: float = 40.0
    relevant_category_keywords: tuple[str, ...] = (
        "dentist", "dental", "doctor", "clinic", "medical", "hospital", "health",
        "lawyer", "legal", "real estate", "property", "school", "college", "education",
        "training", "hotel", "travel", "automotive", "repair", "plumbing", "hvac",
        "marketing", "agency", "consulting", "accounting", "insurance", "financial",
        "retail", "ecommerce", "restaurant", "salon", "fitness", "spa", "logistics",
        "manufacturing", "construction", "home service",
    )
    reference_year: int = field(default_factory=lambda: datetime.now(timezone.utc).year)
    def __post_init__(self) -> None:
        if not 0 <= self.minimum_evidence_coverage <= 100:
            raise ValueError("minimum_evidence_coverage must be between 0 and 100")
        if not 0 <= self.needs_review_minimum <= self.medium_priority_minimum <= self.high_priority_minimum <= 100:
            raise ValueError("score thresholds must satisfy 0 <= review <= medium <= high <= 100")


@dataclass
class LeadDiscoveryRunResult:
    """
    Container for results returned by LeadPipeline.run().
    """
    leads: list[dict[str, Any]] = field(default_factory=list)
    source: str = "google_places"
    fallback_used: bool = False
    fallback_reason: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    result_path: Path | None = None


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = True
    navigation_timeout_ms: int = 30_000
    action_timeout_ms: int = 10_000
    slow_mo_ms: int = 0


@dataclass(frozen=True)
class PlacesConfig:
    api_key: str | None = None
    timeout_seconds: float = 15.0
    max_attempts: int = 2
    retry_delay_seconds: float = 0.15
    @classmethod
    def from_env(cls, settings: DiscoverySettings | None = None) -> "PlacesConfig":
        settings = settings if settings is not None else DiscoverySettings()
        places_key = settings.google_places_api_key
        maps_key = settings.google_maps_api_key
        return cls(
            api_key=(
                (places_key.get_secret_value() if places_key else None)
                or (maps_key.get_secret_value() if maps_key else None)
                or ""
            ).strip()
            or None,
            timeout_seconds=settings.leadsutra_places_timeout_seconds,
            max_attempts=settings.leadsutra_places_max_attempts,
            retry_delay_seconds=settings.leadsutra_places_retry_delay_seconds,
        )
