from pydantic import BaseModel, ConfigDict, Field


class ProposalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lead_id: str = Field(min_length=1, max_length=256)
    business_context: str | None = None
    proposed_service: str | None = None
    approved_product_facts: str | None = None
    approved_pricing: str | None = None
