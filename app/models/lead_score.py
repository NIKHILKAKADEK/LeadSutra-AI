"""LeadSutra lead score result model."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class LeadScoreResult(BaseModel):
    """Structured Lead Scoring result container.

    Stores numerical score, priority level, qualification status, and score breakdown.
    """

    lead_id: str | None = Field(
        default=None,
        description="Unique identifier linking to the parent BusinessLead.",
    )
    external_place_id: str | None = Field(
        default=None,
        description="Provider-agnostic place identifier from discovery source.",
    )
    lead_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Total numerical lead score on a 0 - 100 scale.",
    )
    priority: str = Field(
        ...,
        description="Lead priority rating ('high', 'medium', 'low').",
    )
    qualification_status: str = Field(
        ...,
        description="Lead qualification status ('qualified', 'partially_qualified', 'unqualified').",
    )
    score_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Transparent breakdown of points awarded across the 6 scoring parameters.",
    )
    scored_at: str = Field(
        ...,
        description="ISO 8601 timestamp string when lead was scored.",
    )
    scoring_version: str = Field(
        default="1.0",
        description="Version identifier of the LeadSutra scoring rules.",
    )

    def to_dict(self) -> dict[str, Any]:
        """Return score result attributes as a dictionary."""
        return self.model_dump()
