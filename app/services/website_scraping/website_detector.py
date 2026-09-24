import logging
from typing import Any
import httpx

from app.services.website_scraping.url_validator import validate_and_normalize_url

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class WebsiteDetector:
    """Detects website availability and checks accessibility for a business lead."""

    def __init__(self, timeout_sec: float = 5.0) -> None:
        self.timeout_sec = timeout_sec

    async def detect_and_check(self, raw_url: str | None) -> dict[str, Any]:
        """
        Validates URL and checks HTTP accessibility.

        Returns dict:
        {
            "website_available": bool,
            "website_url": str | None,
            "website_status": str,
            "website_accessible": bool,
            "redirect_url": str | None,
            "http_status_code": int | None,
            "error_message": str | None
        }
        """
        is_valid, normalized_url, status = validate_and_normalize_url(raw_url)

        if not is_valid:
            return {
                "website_available": False if status == "no_website" else True,
                "website_url": None if status == "no_website" else raw_url,
                "website_status": status,  # "no_website" or "invalid_url"
                "website_accessible": False,
                "redirect_url": None,
                "http_status_code": None,
                "error_message": "Invalid URL" if status == "invalid_url" else "No website provided",
            }

        # Check accessibility via HTTP
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_sec,
                follow_redirects=True,
                verify=False,  # Allow self-signed / real-world SSL quirks safely
            ) as client:
                response = await client.get(normalized_url, headers=headers)
                status_code = response.status_code
                final_url = str(response.url)

                if 200 <= status_code < 400:
                    return {
                        "website_available": True,
                        "website_url": normalized_url,
                        "website_status": "accessible",
                        "website_accessible": True,
                        "redirect_url": final_url if final_url != normalized_url else None,
                        "http_status_code": status_code,
                        "error_message": None,
                    }
                elif status_code in (401, 403, 429):
                    return {
                        "website_available": True,
                        "website_url": normalized_url,
                        "website_status": "blocked",
                        "website_accessible": False,
                        "redirect_url": None,
                        "http_status_code": status_code,
                        "error_message": f"Website returned HTTP {status_code} (blocked)",
                    }
                else:
                    return {
                        "website_available": True,
                        "website_url": normalized_url,
                        "website_status": "inaccessible",
                        "website_accessible": False,
                        "redirect_url": None,
                        "http_status_code": status_code,
                        "error_message": f"Website returned HTTP status {status_code}",
                    }
        except httpx.TimeoutException:
            logger.warning("Website request timed out for URL: %s", normalized_url)
            return {
                "website_available": True,
                "website_url": normalized_url,
                "website_status": "timeout",
                "website_accessible": False,
                "redirect_url": None,
                "http_status_code": None,
                "error_message": "Website request timed out",
            }
        except Exception as exc:
            logger.warning("Website check failed for URL %s: %s", normalized_url, str(exc))
            return {
                "website_available": True,
                "website_url": normalized_url,
                "website_status": "inaccessible",
                "website_accessible": False,
                "redirect_url": None,
                "http_status_code": None,
                "error_message": f"Connection error: {type(exc).__name__}",
            }
