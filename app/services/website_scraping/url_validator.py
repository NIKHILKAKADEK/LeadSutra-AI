from urllib.parse import urlparse
import re


def validate_and_normalize_url(url: str | None) -> tuple[bool, str | None, str]:
    """
    Validates and normalizes a business website URL.

    Rules:
    - If URL is empty/None -> returns (False, None, "no_website")
    - Strips whitespace
    - Adds 'https://' if protocol is missing
    - Strips trailing slash
    - Validates scheme (http, https) and netloc syntax
    - Detects invalid patterns (e.g. spaces, malformed TLDs, non-domain strings)

    Returns:
        (is_valid: bool, normalized_url: str | None, status_code: str)
    """
    if not url:
        return False, None, "no_website"

    cleaned = url.strip()
    if not cleaned:
        return False, None, "no_website"

    # Add protocol if missing
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        cleaned = "https://" + cleaned

    try:
        parsed = urlparse(cleaned)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        if scheme not in ("http", "https"):
            return False, None, "invalid_url"

        if not netloc:
            return False, None, "invalid_url"

        # Hostname validation: must contain at least one dot or be localhost (though for business web, TLD required)
        # Netloc can include port
        hostname = netloc.split(":")[0]

        # Basic domain regex check: e.g. example.com, sub.example.co.in
        domain_regex = r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$"
        if not re.match(domain_regex, hostname):
            return False, None, "invalid_url"

        # Reconstruct normalized URL (keep path/query if present, strip trailing slash if path is just /)
        path = parsed.path.rstrip("/")
        normalized = f"{scheme}://{netloc}{path}"
        if parsed.query:
            normalized += f"?{parsed.query}"

        return True, normalized, "valid_url"
    except Exception:
        return False, None, "invalid_url"
