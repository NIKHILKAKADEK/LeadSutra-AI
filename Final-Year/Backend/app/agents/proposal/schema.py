from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.research.schema import LeadAgentRequest, ResearchResult


class ProposalResult(BaseModel):
    business_summary: str
    identified_needs: list[str]
    proposed_solution: str
    deliverables: list[str]
    implementation_timeline: list[str]
    expected_benefits: list[str]
    pricing_suggestion: str
    next_steps: list[str]
    outreach_angle: str = ""
    email_subject_options: list[str] = Field(default_factory=list)
    personalized_email: str = ""
    call_opener: str = ""
    discovery_questions: list[str] = Field(default_factory=list)


class ProposalGenerationRequest(LeadAgentRequest):
    research: ResearchResult | None = None
    retrieved_context: list[str | dict[str, str]] = Field(default_factory=list, max_length=8)


class ProposalGenerationResponse(BaseModel):
    success: bool
    lead_id: str
    business_name: str
    proposal: ProposalResult
