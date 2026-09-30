import re
from typing import Any, List
from urllib.parse import unquote


EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

INVALID_DOMAINS = {
    "example.com",
    "domain.com",
    "yourcompany.com",
    "test.com",
    "email.com",
    "sentry.io",
    "wixpress.com",
    "schema.org",
}

INVALID_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def validate_and_normalize_email(email_raw: str | None) -> str | None:
    """
    Validates and normalizes an email address.
    Lowercases, strips surrounding punctuation/whitespace, filters out dummy/asset patterns.
    """
    if not email_raw:
        return None

    cleaned = unquote(email_raw).strip().lower()
    # Strip surrounding punctuation
    cleaned = cleaned.strip(".,;:()<>[]\"' ")

    if not cleaned:
        return None

    # Check invalid extensions (e.g. image filenames parsed by mistake)
    if any(cleaned.endswith(ext) for ext in INVALID_EXTENSIONS):
        return None

    # Validate syntax
    match = re.match(r"^" + EMAIL_REGEX + r"$", cleaned)
    if not match:
        return None

    domain = cleaned.split("@")[-1]
    if domain in INVALID_DOMAINS:
        return None

    return cleaned


def extract_emails_from_text(text: str) -> list[str]:
    """Finds all email patterns in raw text string, including de-obfuscation."""
    # De-obfuscate patterns like 'user [at] domain.com' or 'user(at)domain.com'
    text_deob = re.sub(r"\s*[\(\[]\s*at\s*[\)\]]\s*", "@", text, flags=re.IGNORECASE)
    text_deob = re.sub(r"\s*[\(\[]\s*dot\s*[\)\]]\s*", ".", text_deob, flags=re.IGNORECASE)

    raw_matches = re.findall(EMAIL_REGEX, text_deob)
    valid_emails = []

    for email_candidate in raw_matches:
        norm = validate_and_normalize_email(email_candidate)
        if norm and norm not in valid_emails:
            valid_emails.append(norm)

    return valid_emails


def extract_emails(
    html_content: str, json_ld_list: list[dict] | None = None, source_url: str = "website"
) -> List[dict[str, Any]]:
    """
    Extracts all public business emails with source, method, and confidence rating.

    Priority order:
    1. Structured JSON-LD (confidence: high)
    2. mailto: links (confidence: high)
    3. Visible text matches (confidence: medium)
    """
    extracted_emails: dict[str, dict[str, Any]] = {}

    # 1. JSON-LD Extraction
    if json_ld_list:
        for obj in json_ld_list:
            if isinstance(obj, dict):
                # Direct telephone/email fields
                raw_email = obj.get("email")
                if isinstance(raw_email, str):
                    norm = validate_and_normalize_email(raw_email)
                    if norm and norm not in extracted_emails:
                        extracted_emails[norm] = {
                            "value": norm,
                            "source": source_url,
                            "method": "json_ld",
                            "confidence": "high",
                        }

                # contactPoint schema
                cp = obj.get("contactPoint")
                if isinstance(cp, dict) and cp.get("email"):
                    norm = validate_and_normalize_email(str(cp["email"]))
                    if norm and norm not in extracted_emails:
                        extracted_emails[norm] = {
                            "value": norm,
                            "source": source_url,
                            "method": "json_ld",
                            "confidence": "high",
                        }
                elif isinstance(cp, list):
                    for item in cp:
                        if isinstance(item, dict) and item.get("email"):
                            norm = validate_and_normalize_email(str(item["email"]))
                            if norm and norm not in extracted_emails:
                                extracted_emails[norm] = {
                                    "value": norm,
                                    "source": source_url,
                                    "method": "json_ld",
                                    "confidence": "high",
                                }

    # 2. mailto: links
    mailto_matches = re.findall(r'href=["\']mailto:([^"\'?]+)', html_content, re.IGNORECASE)
    for mailto_candidate in mailto_matches:
        norm = validate_and_normalize_email(mailto_candidate)
        if norm and norm not in extracted_emails:
            extracted_emails[norm] = {
                "value": norm,
                "source": source_url,
                "method": "mailto",
                "confidence": "high",
            }

    # 3. Visible text content
    text_matches = extract_emails_from_text(html_content)
    for text_email in text_matches:
        if text_email not in extracted_emails:
            extracted_emails[text_email] = {
                "value": text_email,
                "source": source_url,
                "method": "text_regex",
                "confidence": "medium",
            }

    return list(extracted_emails.values())
