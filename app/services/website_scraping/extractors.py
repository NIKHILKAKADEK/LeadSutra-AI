import logging
import re
from typing import Any
from app.services.website_scraping.html_parser import (
    extract_json_ld,
    extract_social_links,
    parse_html_content,
)

logger = logging.getLogger(__name__)


def extract_business_info_from_json_ld(json_ld_list: list[dict]) -> dict[str, Any]:
    """
    Extracts business details from schema.org JSON-LD objects
    (LocalBusiness, Organization, Store, Restaurant, etc.).
    """
    extracted: dict[str, Any] = {
        "name": None,
        "description": None,
        "address": None,
        "phone": None,
        "services": [],
    }

    business_types = {
        "localbusiness",
        "organization",
        "store",
        "restaurant",
        "corporation",
        "medicalbusiness",
        "financialservice",
        "professionalservice",
    }

    for obj in json_ld_list:
        obj_type = obj.get("@type", "")
        if isinstance(obj_type, list):
            obj_type_str = " ".join([str(t).lower() for t in obj_type])
        else:
            obj_type_str = str(obj_type).lower()

        if any(bt in obj_type_str for bt in business_types) or "@context" in obj:
            if not extracted["name"] and obj.get("name"):
                extracted["name"] = str(obj["name"]).strip()

            if not extracted["description"] and obj.get("description"):
                extracted["description"] = str(obj["description"]).strip()

            if not extracted["phone"] and obj.get("telephone"):
                extracted["phone"] = str(obj["telephone"]).strip()

            if not extracted["address"] and obj.get("address"):
                addr = obj["address"]
                if isinstance(addr, str):
                    extracted["address"] = addr.strip()
                elif isinstance(addr, dict):
                    street = addr.get("streetAddress", "")
                    locality = addr.get("addressLocality", "")
                    region = addr.get("addressRegion", "")
                    postal = addr.get("postalCode", "")
                    parts = [p for p in (street, locality, region, postal) if p]
                    if parts:
                        extracted["address"] = ", ".join(parts)

            if obj.get("makesOffer") or obj.get("knowsAbout") or obj.get("services"):
                raw_services = obj.get("makesOffer") or obj.get("knowsAbout") or obj.get("services")
                if isinstance(raw_services, list):
                    for s in raw_services:
                        if isinstance(s, str):
                            extracted["services"].append(s.strip())
                        elif isinstance(s, dict) and s.get("name"):
                            extracted["services"].append(str(s["name"]).strip())

    return extracted


def extract_business_info_from_html(html_str: str, base_url: str) -> dict[str, Any]:
    """
    Extracts business information from HTML content using multi-strategy fallback:
    1. JSON-LD structured data
    2. Meta tags & OpenGraph
    3. HTML Title & Headings (H1/H2)
    4. Social links
    """
    parser = parse_html_content(html_str)

    # 1. JSON-LD structured data
    json_ld_data = extract_json_ld(html_str)
    json_ld_extracted = extract_business_info_from_json_ld(json_ld_data)

    # 2. Meta tags
    meta_tags = parser.meta_tags
    meta_desc = meta_tags.get("description") or meta_tags.get("og:description")
    meta_title = meta_tags.get("og:site_name") or parser.title

    # 3. Description fallback
    description = json_ld_extracted["description"] or meta_desc
    if not description and parser.paragraphs:
        # Use first meaningful paragraph (15+ chars)
        for p in parser.paragraphs:
            if len(p) >= 15:
                description = p
                break

    # 4. Name fallback
    name = json_ld_extracted["name"] or meta_tags.get("og:site_name")
    if not name and parser.headings:
        name = parser.headings[0]
    if not name and parser.title:
        # Strip common site titles like "Home - Acme Corp"
        title_clean = parser.title.split("-")[0].split("|")[0].strip()
        if title_clean:
            name = title_clean

    # 5. Phone & Address fallbacks
    phone = json_ld_extracted["phone"]
    if not phone:
        # Extract phone via regex over visible text/meta tags
        phone_match = re.search(
            r"(\+?\d{1,3}[\s-]?)?\(?\d{3,5}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}", html_str
        )
        if phone_match:
            potential_phone = phone_match.group(0).strip()
            if len(re.sub(r"\D", "", potential_phone)) >= 8:
                phone = potential_phone

    address = json_ld_extracted["address"]

    # 6. Social links
    social_links = extract_social_links(html_str)

    # 7. Services fallback
    services = json_ld_extracted["services"]

    return {
        "name": name,
        "description": description,
        "address": address,
        "phone": phone,
        "services": services,
        "social_links": social_links,
        "website_title": parser.title if parser.title else None,
        "meta_description": meta_desc if meta_desc else None,
    }
