"""Request and response contracts owned by the research agent."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.lead_pipeline.schema import LeadDiscoveryResponse, LeadResult


class SWOTAnalysis(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]


class ResearchSource(BaseModel):
    title: str
    url: str


class ResearchResult(BaseModel):
    business_summary: str
    products_services: list[str]
    target_audience: str
    pain_points: list[str]
    swot: SWOTAnalysis
    ideal_customer_profile: str
    decision_maker_identification: str
    sales_opportunities: list[str]
    provided_facts: list[str]
    reasonable_inferences: list[str]
    missing_information: list[str]
    web_findings: list[str] = Field(default_factory=list)
    research_sources: list[ResearchSource] = Field(default_factory=list)
    contact_page_url: str | None = None
    about_page_url: str | None = None
    operating_hours: list[dict[str, object]] = Field(default_factory=list)
    researched_at: datetime | None = None


class CompetitorRecord(BaseModel):
    name: str
    category: str | None = None
    address: str | None = None
    rating: float | None = None
    review_count: int | None = None
    website: str | None = None
    phone: str | None = None
    source_url: str | None = None
    distance_meters: int | None = None


class CompetitorAnalysis(BaseModel):
    business_name: str
    category: str
    location: str
    status: Literal["complete", "no_results", "unavailable"]
    source: str | None = None
    competitors: list[CompetitorRecord] = Field(default_factory=list)
    radius_meters: int | None = None
    comparison_summary: str
    message: str | None = None
    researched_at: datetime


class LeadAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: LeadResult | None = None
    lead_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def exactly_one_lead_source(self):
        if (self.lead is None) == (self.lead_id is None):
            raise ValueError("Provide exactly one of lead or lead_id.")
        return self


class LeadDiscoverySelection(LeadDiscoveryResponse):
    """A discovery response, optionally naming which result to research."""

    lead_id: str | None = Field(default=None, min_length=1, max_length=256)
