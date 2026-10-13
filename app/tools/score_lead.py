"""Lead qualification and scoring tool wrapping evidence-based scoring rules."""
from __future__ import annotations

from typing import Any

from app.agents.lead_pipeline.schemas import ScoringConfig
from app.agents.lead_pipeline.scoring import score_lead as _score_lead


def score_lead_data(
    lead: dict[str, Any],
    config: ScoringConfig | None = None,
) -> dict[str, Any]:
    """Score and qualify a lead candidate using strictly defined evidence.

    Returns a dict with lead_score, priority, qualification_status, and score_breakdown.
    """
    return _score_lead(lead, config=config or ScoringConfig())
