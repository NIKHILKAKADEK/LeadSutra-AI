
from typing import Any


def _as_dict(value: Any) -> dict:
    """Convert a Pydantic model or dictionary into a dictionary."""
    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)

    return {}


def adapt_lead(raw_lead: dict) -> dict:
    """Normalize canonical LeadSutra leads and legacy lead records."""

    if not isinstance(raw_lead, dict):
        if hasattr(raw_lead, "model_dump"):
            raw_lead = raw_lead.model_dump(mode="json", exclude_none=True)
        else:
            raise ValueError("Lead must be provided as a dictionary or model.")

    # Current canonical structure from the lead-discovery API
    discovery = _as_dict(raw_lead.get("discovery"))
    enrichment = _as_dict(raw_lead.get("enrichment"))
    scoring = _as_dict(raw_lead.get("scoring"))

    # Backward compatibility with the original AI pipeline input
    business = _as_dict(raw_lead.get("business"))
    profile = _as_dict(raw_lead.get("profile"))
    website = _as_dict(raw_lead.get("website_analysis"))
    contacts = _as_dict(raw_lead.get("contacts"))
    legacy_scoring = _as_dict(raw_lead.get("lead_scoring"))

    business_name = (
        discovery.get("business_name")
        or business.get("name")
        or business.get("business_name")
    )

    if not business_name:
        raise ValueError(
            "Lead must contain discovery.business_name "
            "or business.business_name."
        )

    about = enrichment.get("about", "")
    description = (
        enrichment.get("business_description")
        or discovery.get("description")
        or business.get("description")
    )

    return {
        "lead_id": raw_lead.get("lead_id"),
        "business_name": business_name,
        "category": discovery.get("category") or business.get("category"),
        "sub_category": discovery.get("sub_category") or business.get("sub_category"),
        "description": description or about,
        "address": discovery.get("address") or business.get("address"),
        "phone": discovery.get("phone") or business.get("phone"),
        "email": discovery.get("email") or business.get("email"),
        "website": (
            enrichment.get("website_url")
            or discovery.get("website")
            or business.get("website")
        ),
        "rating": discovery.get("rating") or business.get("rating"),
        "review_count": (
            discovery.get("review_count")
            if discovery.get("review_count") is not None
            else business.get("review_count")
        ),
        "latitude": discovery.get("latitude") or business.get("latitude"),
        "longitude": discovery.get("longitude") or business.get("longitude"),
        "services": enrichment.get("services") or profile.get("services", []),
        "products": enrichment.get("products") or profile.get("products", []),
        "target_customers": (
            enrichment.get("target_customers")
            or profile.get("target_customers", [])
        ),
        "about_info": profile.get("about_info"),
        "business_description": description or about,
        "operating_hours": profile.get("operating_hours", {}),
        "website_analysis": website,
        "contacts": {
            **contacts,
            "emails": enrichment.get("emails", contacts.get("emails", [])),
            "phone_numbers": enrichment.get(
                "phone_numbers", contacts.get("phone_numbers", [])
            ),
        },
        "social_links": (
            enrichment.get("social_links")
            or raw_lead.get("social_links", {})
        ),
        "lead_score": (
            scoring.get("lead_score")
            if scoring.get("lead_score") is not None
            else legacy_scoring.get("lead_score")
        ),
        "priority": scoring.get("priority") or legacy_scoring.get("priority"),
        "qualification_status": (
            scoring.get("qualification_status")
            or legacy_scoring.get("qualification_status")
        ),
        "score_breakdown": (
            scoring.get("score_breakdown")
            or legacy_scoring.get("score_breakdown", {})
        ),
    }
