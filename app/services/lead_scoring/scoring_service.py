from datetime import datetime, timezone
import logging
from typing import List, Tuple

from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead
from app.models.lead_score import LeadScoreResult
from app.services.lead_scoring.config import DEFAULT_SCORING_CONFIG, LeadScoringConfig
from app.services.lead_scoring.scorers import (
    score_business_category,
    score_business_size,
    score_contact_availability,
    score_online_presence,
    score_website_availability,
)

logger = logging.getLogger(__name__)


class LeadScoringService:
    """Calculates numerical lead score, transparent breakdown, priority, and qualification status."""

    def __init__(self, config: LeadScoringConfig | None = None) -> None:
        self.config = config or DEFAULT_SCORING_CONFIG

    def score_lead(
        self,
        lead: BusinessLead,
        profile: BusinessProfile | None = None,
        target_category: str | None = None,
    ) -> Tuple[BusinessLead, LeadScoreResult]:
        """
        Scores a single BusinessLead instance using the 6 scoring parameters.
        Returns updated BusinessLead and LeadScoreResult model.
        """
        # 1. Parameter Scoring
        cat_score = score_business_category(
            lead.category, target_category or lead.category, self.config
        )
        web_score = score_website_availability(lead.website_status, lead.website, self.config)
        onl_score = score_online_presence(lead.social_links, lead.website_status, self.config)
        con_score = score_contact_availability(
            lead.email, lead.phone, lead.contact_person, lead.contact_emails, self.config
        )
        siz_score = score_business_size(profile, self.config)

        breakdown = {
            "business_category": cat_score,
            "website_availability": web_score,
            "online_presence": onl_score,
            "contact_availability": con_score,
            "business_size": siz_score,
        }

        total_score = sum(breakdown.values())
        total_score = max(0, min(100, total_score))  # Clamp 0-100

        # 2. Priority & Qualification Assignment
        if total_score >= self.config.high_priority_threshold:
            priority = "high"
            qualification = "qualified"
        elif total_score >= self.config.medium_priority_threshold:
            priority = "medium"
            qualification = "partially_qualified"
        else:
            priority = "low"
            qualification = "unqualified"

        # 3. Create Result Model
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_id = lead.external_place_id or f"lead_{hash(lead.name)}"

        score_result = LeadScoreResult(
            lead_id=lead_id,
            external_place_id=lead.external_place_id,
            lead_score=total_score,
            priority=priority,
            qualification_status=qualification,
            score_breakdown=breakdown,
            scored_at=now_iso,
            scoring_version=self.config.scoring_version,
        )

        # 4. Update BusinessLead instance
        lead_dict = lead.model_dump()
        lead_dict["lead_score"] = total_score
        lead_dict["priority"] = priority
        lead_dict["qualification_status"] = qualification
        lead_dict["score_breakdown"] = breakdown
        updated_lead = BusinessLead(**lead_dict)

        return updated_lead, score_result

    def score_leads(
        self,
        leads: List[BusinessLead],
        profiles: List[BusinessProfile] | None = None,
        target_category: str | None = None,
    ) -> Tuple[List[BusinessLead], List[LeadScoreResult]]:
        """
        Batch scores a list of BusinessLead instances independently.
        """
        profiles_by_id = {}
        if profiles:
            for p in profiles:
                if p.external_place_id:
                    profiles_by_id[p.external_place_id] = p
                elif p.lead_id:
                    profiles_by_id[p.lead_id] = p

        scored_leads: List[BusinessLead] = []
        score_results: List[LeadScoreResult] = []

        for lead in leads:
            try:
                prof = None
                if lead.external_place_id:
                    prof = profiles_by_id.get(lead.external_place_id)

                updated_lead, score_result = self.score_lead(
                    lead, profile=prof, target_category=target_category
                )
                scored_leads.append(updated_lead)
                score_results.append(score_result)
            except Exception as exc:
                logger.error("Failed scoring for lead %s: %s", lead.name, str(exc))
                # Fallback minimal result
                lead_dict = lead.model_dump()
                lead_dict["lead_score"] = 0
                lead_dict["priority"] = "low"
                lead_dict["qualification_status"] = "unqualified"
                fallback_lead = BusinessLead(**lead_dict)

                fallback_result = LeadScoreResult(
                    lead_id=lead.external_place_id or f"lead_{hash(lead.name)}",
                    external_place_id=lead.external_place_id,
                    lead_score=0,
                    priority="low",
                    qualification_status="unqualified",
                    score_breakdown={"business_category": 0},
                    scored_at=datetime.now(timezone.utc).isoformat(),
                    scoring_version=self.config.scoring_version,
                )
                scored_leads.append(fallback_lead)
                score_results.append(fallback_result)

        return scored_leads, score_results


# Convenience functions
def score_lead(
    lead: BusinessLead,
    profile: BusinessProfile | None = None,
    target_category: str | None = None,
) -> Tuple[BusinessLead, LeadScoreResult]:
    service = LeadScoringService()
    return service.score_lead(lead, profile=profile, target_category=target_category)


def score_leads(
    leads: List[BusinessLead],
    profiles: List[BusinessProfile] | None = None,
    target_category: str | None = None,
) -> Tuple[List[BusinessLead], List[LeadScoreResult]]:
    service = LeadScoringService()
    return service.score_leads(leads, profiles=profiles, target_category=target_category)
