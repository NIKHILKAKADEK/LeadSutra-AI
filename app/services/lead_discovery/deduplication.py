from typing import List, Tuple
from app.models.lead import BusinessLead
from app.services.lead_discovery.normalizers import (
    haversine_distance_meters,
    normalize_address,
    normalize_business_name,
    normalize_phone,
    normalize_website_domain,
)


def are_leads_duplicate(
    lead1: BusinessLead,
    lead2: BusinessLead,
    distance_threshold_m: float = 100.0,
) -> Tuple[bool, str]:
    """
    Determines if two BusinessLead objects represent the same physical business.

    Matches based on:
    1. Phone match (exact match on normalized phone number)
    2. Domain match (exact match on normalized website domain)
    3. Name + Geo proximity match (normalized name match AND distance <= distance_threshold_m)
    4. Name + Address match (normalized name match AND normalized address match)

    Returns:
        (is_duplicate: bool, match_reason: str)
    """
    # 1. Phone match
    phone1 = normalize_phone(lead1.phone)
    phone2 = normalize_phone(lead2.phone)
    if phone1 and phone2 and phone1 == phone2:
        return True, "phone_match"

    # 2. Domain match
    domain1 = normalize_website_domain(lead1.website)
    domain2 = normalize_website_domain(lead2.website)
    if domain1 and domain2 and domain1 == domain2:
        return True, "domain_match"

    # Normalize business names for rules 3 and 4
    name1 = normalize_business_name(lead1.name)
    name2 = normalize_business_name(lead2.name)

    names_match = False
    if name1 and name2:
        if name1 == name2 or name1 in name2 or name2 in name1:
            names_match = True

    if names_match:
        # 3. Name + Geo proximity match
        dist = haversine_distance_meters(
            lead1.latitude, lead1.longitude, lead2.latitude, lead2.longitude
        )
        if dist is not None and dist <= distance_threshold_m:
            return True, "name_geo_match"

        # 4. Name + Address match
        addr1 = normalize_address(lead1.address)
        addr2 = normalize_address(lead2.address)
        if addr1 and addr2:
            if addr1 == addr2 or addr1 in addr2 or addr2 in addr1:
                return True, "name_address_match"

    return False, "no_match"


def merge_leads(lead1: BusinessLead, lead2: BusinessLead) -> BusinessLead:
    """
    Merges two duplicate BusinessLead objects into a single cohesive lead.

    Preference rule:
    - Primary provider is 'google' over 'foursquare'.
    - If one lead is from Google, it serves as the base.
    - Missing/null fields in the base lead are filled from the secondary lead.
    """
    # Determine primary vs secondary
    if lead1.source == "google":
        primary, secondary = lead1, lead2
    elif lead2.source == "google":
        primary, secondary = lead2, lead1
    else:
        primary, secondary = lead1, lead2

    # Create new lead dictionary starting from primary values
    merged_data = {
        "name": primary.name or secondary.name,
        "category": primary.category or secondary.category,
        "address": primary.address or secondary.address,
        "phone": primary.phone or secondary.phone,
        "email": primary.email or secondary.email,
        "website": primary.website or secondary.website,
        "rating": primary.rating if primary.rating is not None else secondary.rating,
        "latitude": primary.latitude if primary.latitude is not None else secondary.latitude,
        "longitude": primary.longitude if primary.longitude is not None else secondary.longitude,
        "external_place_id": primary.external_place_id or secondary.external_place_id,
        "source": primary.source,
    }

    # Merge raw_data metadata
    merged_raw = dict(primary.raw_data or {})
    merged_raw["merged_sources"] = [
        {"source": primary.source, "external_place_id": primary.external_place_id},
        {"source": secondary.source, "external_place_id": secondary.external_place_id},
    ]

    if secondary.raw_data:
        merged_raw[f"{secondary.source}_raw_data"] = secondary.raw_data

    merged_data["raw_data"] = merged_raw

    return BusinessLead(**merged_data)


def deduplicate_leads(
    leads: List[BusinessLead], distance_threshold_m: float = 100.0
) -> List[BusinessLead]:
    """
    Takes a list of BusinessLead objects, identifies duplicates, merges them,
    and returns a deduplicated list of leads.
    """
    if not leads:
        return []

    deduped: List[BusinessLead] = []

    for lead in leads:
        matched_index = None
        for i, existing in enumerate(deduped):
            is_dup, _ = are_leads_duplicate(lead, existing, distance_threshold_m)
            if is_dup:
                matched_index = i
                break

        if matched_index is not None:
            # Merge into existing lead
            deduped[matched_index] = merge_leads(deduped[matched_index], lead)
        else:
            deduped.append(lead)

    return deduped
