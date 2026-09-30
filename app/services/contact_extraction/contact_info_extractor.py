import logging
from typing import Any
from urllib.parse import urljoin, urlparse

from app.services.contact_extraction.email_extractor import extract_emails
from app.services.contact_extraction.person_extractor import extract_contact_person
from app.services.contact_extraction.phone_extractor import extract_phones
from app.services.website_scraping.extractors import extract_business_info_from_html
from app.services.website_scraping.html_parser import extract_json_ld, parse_html_content

logger = logging.getLogger(__name__)


def find_contact_and_about_urls(html_content: str, base_url: str) -> tuple[str | None, str | None]:
    """Finds exact contact page and about page URLs from website HTML."""
    parser = parse_html_content(html_content)
    base_netloc = urlparse(base_url).netloc.lower()

    contact_url = None
    about_url = None

    for href in parser.hrefs:
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower() == base_netloc:
            path = parsed.path.lower()
            if not contact_url and "contact" in path:
                contact_url = full_url.split("#")[0]
            if not about_url and ("about" in path or "team" in path or "company" in path):
                about_url = full_url.split("#")[0]

        if contact_url and about_url:
            break

    return contact_url, about_url


def extract_operating_hours(json_ld_list: list[dict]) -> str | dict | None:
    """Extracts operating hours from schema.org JSON-LD if available."""
    if not json_ld_list:
        return None

    for obj in json_ld_list:
        if isinstance(obj, dict):
            hours = obj.get("openingHours") or obj.get("openingHoursSpecification")
            if hours:
                return hours
    return None


def extract_all_contact_and_business_info(
    html_content: str, base_url: str
) -> dict[str, Any]:
    """
    Main extraction orchestrator for Task 6.

    Extracts:
    - emails & primary_email
    - phones & primary_phone
    - contact_person
    - contact_page_url & about_page_url
    - operating_hours
    - social_links
    - business_info (name, description, services, address)
    - extraction_metadata (provenance & confidence)
    """
    json_ld_list = extract_json_ld(html_content)

    # 1. Emails
    email_records = extract_emails(html_content, json_ld_list, source_url=base_url)
    primary_email = email_records[0]["value"] if email_records else None
    contact_emails = [rec["value"] for rec in email_records]

    # 2. Phones
    phone_records = extract_phones(html_content, json_ld_list, source_url=base_url)
    primary_phone = phone_records[0]["value"] if phone_records else None

    # 3. Contact person
    person_name = extract_contact_person(html_content, json_ld_list)

    # 4. Contact & About URLs
    contact_url, about_url = find_contact_and_about_urls(html_content, base_url)

    # 5. Operating hours
    hours = extract_operating_hours(json_ld_list)

    # 6. General business info & social links from Task 5 extractors
    binfo = extract_business_info_from_html(html_content, base_url)

    # 7. Metadata provenance tracking
    extraction_metadata = {
        "extracted_from_url": base_url,
        "email_extracted": bool(primary_email),
        "phone_extracted": bool(primary_phone),
        "person_extracted": bool(person_name),
        "email_details": email_records,
        "phone_details": phone_records,
    }

    return {
        "primary_email": primary_email,
        "contact_emails": contact_emails,
        "email_records": email_records,
        "primary_phone": primary_phone,
        "phone_records": phone_records,
        "contact_person": person_name,
        "contact_page_url": contact_url,
        "about_page_url": about_url,
        "operating_hours": hours,
        "social_links": binfo["social_links"],
        "description": binfo["description"],
        "address": binfo["address"],
        "services": binfo["services"],
        "extraction_metadata": extraction_metadata,
    }
