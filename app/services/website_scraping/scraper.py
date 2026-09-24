import logging
from typing import Any
import httpx

from app.services.website_scraping.extractors import extract_business_info_from_html
from app.services.website_scraping.html_parser import extract_relevant_internal_links
from app.services.website_scraping.playwright_scraper import scrape_with_playwright
from app.services.website_scraping.website_detector import (
    DEFAULT_USER_AGENT,
    WebsiteDetector,
)

logger = logging.getLogger(__name__)


class WebsiteScraper:
    """Scrapes business websites for business details, description, services, and social links."""

    def __init__(self, timeout_sec: float = 6.0) -> None:
        self.timeout_sec = timeout_sec
        self.detector = WebsiteDetector(timeout_sec=timeout_sec)

    async def scrape_website(
        self, raw_url: str | None, check_internal_pages: bool = True
    ) -> dict[str, Any]:
        """
        Main entry point for website scraping.

        Flow:
        1. Website Detection & Accessibility Check
        2. Homepage HTTP Fetch
        3. Fallback to Playwright if JS rendering required
        4. Data Extraction (JSON-LD, Meta, Headings, Text, Socials)
        5. Internal page enrichment (/about, /contact, /services)
        6. Return structured result
        """
        # Step 1: Detect & Check Accessibility
        detection = await self.detector.detect_and_check(raw_url)

        if not detection["website_available"]:
            return {
                "website": None,
                "website_available": False,
                "website_accessible": False,
                "scrape_status": "no_website",
                "scraped_data": {},
                "scrape_error": "No website provided",
            }

        normalized_url = detection["website_url"]

        if not detection["website_accessible"]:
            return {
                "website": normalized_url,
                "website_available": True,
                "website_accessible": False,
                "scrape_status": detection["website_status"],  # "inaccessible", "timeout", "blocked", "invalid_url"
                "scraped_data": {},
                "scrape_error": detection["error_message"],
            }

        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

        # Step 2: Fetch Homepage HTML
        html_content = ""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_sec,
                follow_redirects=True,
                verify=False,
            ) as client:
                res = await client.get(normalized_url, headers=headers)
                if res.status_code == 200:
                    html_content = res.text
                elif res.status_code in (401, 403, 429):
                    return {
                        "website": normalized_url,
                        "website_available": True,
                        "website_accessible": False,
                        "scrape_status": "blocked",
                        "scraped_data": {},
                        "scrape_error": f"HTTP {res.status_code} blocked",
                    }
                else:
                    return {
                        "website": normalized_url,
                        "website_available": True,
                        "website_accessible": False,
                        "scrape_status": "inaccessible",
                        "scraped_data": {},
                        "scrape_error": f"HTTP status {res.status_code}",
                    }
        except httpx.TimeoutException:
            return {
                "website": normalized_url,
                "website_available": True,
                "website_accessible": False,
                "scrape_status": "timeout",
                "scraped_data": {},
                "scrape_error": "Website request timed out",
            }
        except Exception as exc:
            return {
                "website": normalized_url,
                "website_available": True,
                "website_accessible": False,
                "scrape_status": "failed",
                "scraped_data": {},
                "scrape_error": f"Scrape connection failed: {type(exc).__name__}",
            }

        # Step 3: Check JS Rendering Requirement & Fallback to Playwright
        if (
            not html_content
            or len(html_content.strip()) < 150
            or ("<script" in html_content.lower() and "<p" not in html_content.lower())
        ):
            pw_result = await scrape_with_playwright(normalized_url, timeout_ms=int(self.timeout_sec * 1000))
            if pw_result and pw_result.get("html"):
                html_content = pw_result["html"]

        # Step 4: Homepage Data Extraction
        scraped_info = extract_business_info_from_html(html_content, normalized_url)

        # Step 5: Internal Page Enrichment (About, Contact, Services)
        if check_internal_pages:
            internal_links = extract_relevant_internal_links(html_content, normalized_url)
            for sub_link in internal_links[:2]:  # Limit to 2 sub-pages max
                try:
                    async with httpx.AsyncClient(
                        timeout=3.0,
                        follow_redirects=True,
                        verify=False,
                    ) as sub_client:
                        sub_res = await sub_client.get(sub_link, headers=headers)
                        if sub_res.status_code == 200:
                            sub_info = extract_business_info_from_html(sub_res.text, sub_link)

                            # Enrich missing fields
                            if not scraped_info["description"] and sub_info["description"]:
                                scraped_info["description"] = sub_info["description"]

                            if not scraped_info["phone"] and sub_info["phone"]:
                                scraped_info["phone"] = sub_info["phone"]

                            if not scraped_info["address"] and sub_info["address"]:
                                scraped_info["address"] = sub_info["address"]

                            for platform, link in sub_info["social_links"].items():
                                if platform not in scraped_info["social_links"]:
                                    scraped_info["social_links"][platform] = link

                            for svc in sub_info["services"]:
                                if svc not in scraped_info["services"]:
                                    scraped_info["services"].append(svc)
                except Exception:
                    continue

        return {
            "website": normalized_url,
            "website_available": True,
            "website_accessible": True,
            "scrape_status": "success",
            "scraped_data": scraped_info,
            "scrape_error": None,
        }
