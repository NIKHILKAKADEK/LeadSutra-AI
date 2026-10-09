"""Minimal artifact interface for existing declared Voice context fields.

Proposal generation and approval are not implemented by this contract. Producers
must write trusted, approved content server-side; the public call API accepts none.
"""

from pydantic import BaseModel, ConfigDict, Field


class ProposalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lead_id: str = Field(min_length=1, max_length=256)
    business_context: str | None = None
    proposed_service: str | None = None
    approved_product_facts: str | None = None
    approved_pricing: str | None = None
