import re
from typing import Any
from app.models.business_profile import BusinessProfile
from app.services.lead_scoring.config import DEFAULT_SCORING_CONFIG, LeadScoringConfig


def score_business_category(
    lead_category: str | None,
    target_category: str | None,
    config: LeadScoringConfig = DEFAULT_SCORING_CONFIG,
) -> int:
    """Evaluates business category match against requested/target category."""
    if not lead_category:
        return 0

    if not target_category:
        # Category exists on lead, award moderate score if no specific target requested
        return int(config.max_business_category * 0.6)  # 15 pts

    c_lead = lead_category.strip().lower()
    c_target = target_category.strip().lower()

    if c_lead == c_target or c_target in c_lead or c_lead in c_target:
        return config.max_business_category  # 25 pts

    # Token overlap or prefix match check (e.g. "Dental Clinic" vs "Dentist")
    lead_tokens = set(re.findall(r"\w+", c_lead))
    target_tokens = set(re.findall(r"\w+", c_target))
    if lead_tokens.intersection(target_tokens):
        return int(config.max_business_category * 0.75)  # 18 pts

    for lt in lead_tokens:
        for tt in target_tokens:
            if len(lt) >= 4 and len(tt) >= 4 and (lt[:4] == tt[:4] or lt in tt or tt in lt):
                return int(config.max_business_category * 0.75)  # 18 pts

    return int(config.max_business_category * 0.3)  # 7 pts


def score_website_availability(
    website_status: str | None,
    website_url: str | None,
    config: LeadScoringConfig = DEFAULT_SCORING_CONFIG,
) -> int:
    """Evaluates website availability and accessibility."""
    if not website_url or website_status == "no_website":
        return 0

    if website_status in ("accessible", "success", "valid_url"):
        return config.max_website_availability  # 20 pts

    if website_status in ("inaccessible", "blocked", "timeout"):
        return round(config.max_website_availability * 0.45)  # 9 pts

    if website_status == "invalid_url":
        return 0

    # Default fallback when URL is present but status not explicit
    return round(config.max_website_availability * 0.66)  # 13 pts


def score_online_presence(
    social_links: dict[str, str] | None,
    website_status: str | None,
    config: LeadScoringConfig = DEFAULT_SCORING_CONFIG,
) -> int:
    """Evaluates digital footprint and social media presence."""
    socials = social_links or {}
    social_count = len(socials)

    if social_count >= 3:
        return config.max_online_presence  # 20 pts
    elif social_count in (1, 2):
        return round(config.max_online_presence * (2.0 / 3.0))  # 13 pts
    elif website_status in ("accessible", "success"):
        return round(config.max_online_presence * (1.0 / 3.0))  # 7 pts

    return 0


def score_contact_availability(
    email: str | None,
    phone: str | None,
    contact_person: str | None,
    contact_emails: list[str] | None = None,
    config: LeadScoringConfig = DEFAULT_SCORING_CONFIG,
) -> int:
    """Evaluates contactability and available communication channels."""
    has_email = bool(email or (contact_emails and len(contact_emails) > 0))
    has_phone = bool(phone)
    has_person = bool(contact_person)

    if has_email and has_phone and has_person:
        return config.max_contact_availability  # 25 pts

    if (has_email and has_phone) or (has_person and (has_email or has_phone)):
        return int(config.max_contact_availability * 0.75)  # 18 pts

    if has_email or has_phone:
        return int(config.max_contact_availability * 0.5)  # 12 pts

    return 0


def score_business_size(
    profile: BusinessProfile | None,
    config: LeadScoringConfig = DEFAULT_SCORING_CONFIG,
) -> int:
    """Evaluates business size signals based on profile offerings and online presence."""
    if not profile:
        return int(config.max_business_size * 0.2)  # 2 pts (missing data rule)

    service_count = len(profile.services or [])
    product_count = len(profile.products or [])
    target_count = len(profile.target_customers or [])

    if service_count >= 5 or product_count >= 5 or target_count >= 2:
        return config.max_business_size  # 10 pts

    if service_count >= 1 or product_count >= 1 or profile.description:
        return int(config.max_business_size * 0.6)  # 6 pts

    return int(config.max_business_size * 0.2)  # 2 pts
