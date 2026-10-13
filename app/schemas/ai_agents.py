"""Request contracts for independently invoked AI agents."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.lead_pipeline.schemas import LeadDiscoveryResponse, LeadResult
from app.models.proposal import ProposalResult
from app.models.research import ResearchResult


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


class ProposalGenerationRequest(LeadAgentRequest):
    research: ResearchResult | None = None
    retrieved_context: list[str | dict[str, str]] = Field(default_factory=list, max_length=8)


class ProposalGenerationResponse(BaseModel):
    success: bool
    lead_id: str
    business_name: str
    proposal: ProposalResult


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    k: int = Field(default=3, ge=1, le=8)
