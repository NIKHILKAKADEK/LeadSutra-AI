import math
import re
from urllib.parse import urlparse


def normalize_phone(phone_str: str | None) -> str | None:
    """
    Normalizes a phone number string to a clean, standardized format.
    Strips spaces, dashes, parentheses, dots.
    If the number starts with +, retains +.
    Handles 10-digit Indian numbers by prefixing +91 if appropriate, or standardizes digits.
    Returns None if input is empty or invalid.
    """
    if not phone_str:
        return None

    cleaned = phone_str.strip()
    if not cleaned:
        return None

    is_plus = cleaned.startswith("+")
    digits = re.sub(r"\D", "", cleaned)

    if not digits:
        return None

    if len(digits) == 11 and digits.startswith("0") and not is_plus:
        digits = digits[1:]

    # Handle 10-digit Indian numbers (defaulting to +91 when appropriate) or plain 10 digits
    if len(digits) == 10 and not is_plus:
        return f"+91{digits}"
    elif is_plus:
        return f"+{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"

    return f"+{digits}" if is_plus else digits


def normalize_website_domain(url: str | None) -> str | None:
    """
    Extracts and normalizes the domain from a website URL.
    Strips http://, https://, www., paths, parameters, port, and trailing slashes.
    Returns lowercase domain string, or None if invalid/empty.
    """
    if not url:
        return None

    url_str = url.strip().lower()
    if not url_str:
        return None

    if not (url_str.startswith("http://") or url_str.startswith("https://")):
        url_str = "http://" + url_str

    try:
        parsed = urlparse(url_str)
        domain = parsed.netloc or parsed.path.split("/")[0]
        # Remove port if present
        domain = domain.split(":")[0]
        # Remove www.
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.strip() if domain.strip() else None
    except Exception:
        return None


def normalize_business_name(name: str | None) -> str | None:
    """
    Normalizes a business name for comparison:
    - Lowercases text
    - Removes common legal entity suffixes (Pvt Ltd, Ltd, LLC, Inc, Corp, Co, etc.)
    - Removes special characters and punctuation
    - Strips extra spaces
    """
    if not name:
        return None

    cleaned = name.strip().lower()
    if not cleaned:
        return None

    # Strip legal entity suffixes
    legal_suffixes = [
        r"\bpvt\.?\s*ltd\.?\b",
        r"\bprivate\s*limited\b",
        r"\bltd\.?\b",
        r"\blimited\b",
        r"\binc\.?\b",
        r"\bincorporated\b",
        r"\bllc\.?\b",
        r"\bcorp\.?\b",
        r"\bcorporation\b",
        r"\bco\.?\b",
        r"\bcompany\b",
    ]

    for suffix in legal_suffixes:
        cleaned = re.sub(suffix, "", cleaned)

    # Remove non-alphanumeric characters (keep spaces)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)

    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned if cleaned else None


def normalize_address(address: str | None) -> str | None:
    """
    Normalizes an address string:
    - Lowercases text
    - Standardizes common terms (st -> street, rd -> road, ave -> avenue, etc.)
    - Removes punctuation and extra spaces
    """
    if not address:
        return None

    cleaned = address.strip().lower()
    if not cleaned:
        return None

    # Replace common address abbreviations
    abbreviations = {
        r"\bst\.?\b": "street",
        r"\brd\.?\b": "road",
        r"\bave\.?\b": "avenue",
        r"\bblvd\.?\b": "boulevard",
        r"\bdr\.?\b": "drive",
        r"\bln\.?\b": "lane",
        r"\bapt\.?\b": "apartment",
        r"\bste\.?\b": "suite",
        r"\bfl\.?\b": "floor",
        r"\bno\.?\b": "number",
    }

    for abbr, full in abbreviations.items():
        cleaned = re.sub(abbr, full, cleaned)

    # Remove punctuation except alphanumeric and spaces
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned if cleaned else None


def haversine_distance_meters(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float | None:
    """
    Calculates the great-circle distance between two points on the Earth in meters
    using the Haversine formula.
    Returns None if any coordinate is missing.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    # Radius of Earth in meters
    R = 6371000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c
