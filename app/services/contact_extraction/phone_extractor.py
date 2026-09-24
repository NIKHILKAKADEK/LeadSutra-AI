import re
from typing import Any, List
from urllib.parse import unquote
from app.services.lead_discovery.normalizers import normalize_phone


def extract_phones(
    html_content: str, json_ld_list: list[dict] | None = None, source_url: str = "website"
) -> List[dict[str, Any]]:
    """
    Extracts all public business phone numbers with source, method, and confidence rating.

    Priority order:
    1. Structured JSON-LD (confidence: high)
    2. tel: links (confidence: high)
    3. Visible text matches (confidence: medium)
    """
    extracted_phones: dict[str, dict[str, Any]] = {}

    # 1. JSON-LD Extraction
    if json_ld_list:
        for obj in json_ld_list:
            if isinstance(obj, dict):
                raw_phone = obj.get("telephone")
                if isinstance(raw_phone, str):
                    norm = normalize_phone(raw_phone)
                    if norm and norm not in extracted_phones:
                        extracted_phones[norm] = {
                            "value": norm,
                            "display_value": raw_phone.strip(),
                            "source": source_url,
                            "method": "json_ld",
                            "confidence": "high",
                        }

    # 2. tel: links
    tel_matches = re.findall(r'href=["\']tel:([^"\'?]+)', html_content, re.IGNORECASE)
    for tel_candidate in tel_matches:
        raw_clean = unquote(tel_candidate).strip()
        norm = normalize_phone(raw_clean)
        if norm and norm not in extracted_phones:
            extracted_phones[norm] = {
                "value": norm,
                "display_value": raw_clean,
                "source": source_url,
                "method": "tel_link",
                "confidence": "high",
            }

    # 3. Regex over visible text (strip HTML tags first to avoid matching inside attributes)
    clean_text = re.sub(r"<[^>]+>", " ", html_content)
    phone_pattern = r"\+?\d{1,3}[\s-]?\(?\d{3,5}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}"
    for match in re.finditer(phone_pattern, clean_text):
        raw_val = match.group(0).strip()
        if raw_val:
            norm = normalize_phone(raw_val)
            if norm and norm not in extracted_phones:
                # Avoid adding partial substrings of numbers already extracted
                is_sub = False
                for existing_norm in extracted_phones:
                    if norm in existing_norm or existing_norm in norm:
                        is_sub = True
                        break
                if not is_sub:
                    extracted_phones[norm] = {
                        "value": norm,
                        "display_value": raw_val,
                        "source": source_url,
                        "method": "text_regex",
                        "confidence": "medium",
                    }

    return list(extracted_phones.values())
