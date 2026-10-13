"""Contact extraction utilities for parsing emails and phone numbers from text/HTML."""
from __future__ import annotations

import re
from typing import Any

from app.agents.lead_pipeline.pipeline import EMAIL_RE, _valid_email
from app.models.leads import normalize_indian_mobile

PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?91[\s.-]*)?[6-9](?:[\s.-]?\d){9}(?!\d)|(?<!\d)(?:\+?1[\-\s]?)?\(?\d{3}\)?[\-\s]?\d{3}[\-\s]?\d{4}(?!\d)",
    re.IGNORECASE,
)


def extract_emails_from_text(text: str) -> list[str]:
    """Extract and validate distinct email addresses from unstructured text."""
    if not text:
        return []
    matches = EMAIL_RE.findall(text)
    validated = []
    seen = set()
    for raw in matches:
        clean = _valid_email(raw)
        if clean and clean not in seen:
            seen.add(clean)
            validated.append(clean)
    return validated


def extract_phones_from_text(text: str) -> list[str]:
    """Extract distinct phone numbers from unstructured text."""
    if not text:
        return []
    matches = PHONE_PATTERN.findall(text)
    validated = []
    seen = set()
    for raw in matches:
        clean = re.sub(r"[\s\-\(\)]", "", raw)
        try:
            norm = normalize_indian_mobile(clean)
            if norm not in seen:
                seen.add(norm)
                validated.append(norm)
        except ValueError:
            if clean and clean not in seen:
                seen.add(clean)
                validated.append(clean)
    return validated
