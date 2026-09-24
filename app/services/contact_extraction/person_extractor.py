import re
from typing import Any
from app.services.website_scraping.html_parser import parse_html_content

GENERIC_ROLES = {
    "support",
    "admin",
    "administrator",
    "sales",
    "info",
    "helpdesk",
    "customer service",
    "manager",
    "receptionist",
}

HONORIFICS = r"\b(?:dr|mr|mrs|ms|prof|ca|adv)\.?"
TITLE_KEYWORDS = r"\b(?:founder|co-founder|director|ceo|president|owner|proprietor|partner|head|lead|manager|chairperson)\b"


def extract_contact_person(
    html_content: str, json_ld_list: list[dict] | None = None
) -> str | None:
    """
    Extracts a primary contact person's name if explicitly present on the website.

    Sources:
    1. Structured JSON-LD (founder, owner, contactPoint with Person type)
    2. HTML content patterns (Honorifics + Name or Name + Title/Role)

    Returns name string or None. Does NOT guess or infer missing names.
    """
    # 1. JSON-LD Person extraction
    if json_ld_list:
        for obj in json_ld_list:
            if isinstance(obj, dict):
                # Check founder / owner / author
                for role_key in ("founder", "owner", "author", "employee"):
                    val = obj.get(role_key)
                    if isinstance(val, dict) and val.get("name"):
                        person_name = str(val["name"]).strip()
                        if person_name.lower() not in GENERIC_ROLES:
                            return person_name
                    elif isinstance(val, str) and val.strip().lower() not in GENERIC_ROLES:
                        return val.strip()

                # Check Person schema type directly
                if obj.get("@type") == "Person" and obj.get("name"):
                    person_name = str(obj["name"]).strip()
                    if person_name.lower() not in GENERIC_ROLES:
                        return person_name

    # 2. HTML text parsing
    parser = parse_html_content(html_content)

    candidates = parser.headings + parser.paragraphs

    if not candidates:
        clean_text = re.sub(r"<[^>]+>", " ", html_content)
        candidates = [clean_text]

    for text in candidates:
        text_clean = text.strip()

        # Honorific + Name: e.g. Dr. Jatin Shewale
        hon_match = re.search(
            r"((?:" + HONORIFICS + r")\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text_clean, re.IGNORECASE
        )
        if hon_match:
            candidate_name = hon_match.group(1).strip()
            if not any(gr in candidate_name.lower() for gr in GENERIC_ROLES):
                return candidate_name

        # Name + Role: e.g., "Nikhil Kakde - Founder & CEO"
        role_match = re.search(
            r"((?:(?:" + HONORIFICS + r")\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*[-–|,]\s*" + TITLE_KEYWORDS, text_clean, re.IGNORECASE
        )
        if role_match:
            candidate_name = role_match.group(1).strip()
            if not any(gr in candidate_name.lower() for gr in GENERIC_ROLES):
                return candidate_name

    return None
