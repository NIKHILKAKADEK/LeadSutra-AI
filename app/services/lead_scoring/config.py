"""Centralized configuration for LeadSutra Lead Scoring system."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LeadScoringConfig:
    """Configurable scoring weights and priority thresholds.

    Total max points across all 5 parameters = 100 points.
    """

    # Scoring Weights (Max Points)
    max_business_category: int = 25
    max_website_availability: int = 20
    max_online_presence: int = 20
    max_contact_availability: int = 25
    max_business_size: int = 10

    # Priority & Qualification Thresholds
    high_priority_threshold: int = 75
    medium_priority_threshold: int = 50

    # Version tag
    scoring_version: str = "1.0"


DEFAULT_SCORING_CONFIG = LeadScoringConfig()
