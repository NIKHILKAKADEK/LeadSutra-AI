"""Website scraping tool wrapping HTTPX, BeautifulSoup, and Playwright rendering."""
from __future__ import annotations

import logging
from typing import Any

from app.agents.lead_pipeline.schemas import (
    BusinessRecord,
    WebsiteCrawlerConfig,
    WebsiteCrawlResult,
    WebsiteStatus,
)
from app.integrations.website_fetcher import WebsiteCrawler, normalize_url

logger = logging.getLogger(__name__)


async def scrape_website(
    url: str,
    business_name: str = "Unknown Business",
    *,
    config: WebsiteCrawlerConfig | None = None,
) -> WebsiteCrawlResult:
    """Fetch and extract clean website content for a business URL.

    Uses HTTPX + BeautifulSoup for accessible static content, falling back to
    Playwright for dynamic JavaScript-rendered single-page applications.
    """
    clean_url = normalize_url(url)
    if not clean_url:
        result = WebsiteCrawlResult(website_url=url, website_status=WebsiteStatus.INVALID)
        return result

    crawler = WebsiteCrawler(config=config)
    record = BusinessRecord(
        lead_id="website-scrape",
        business_name=business_name,
        website=clean_url,
    )
    return await crawler.crawl(record)
