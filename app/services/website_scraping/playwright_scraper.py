import logging
from typing import Any

logger = logging.getLogger(__name__)


async def scrape_with_playwright(url: str, timeout_ms: int = 8000) -> dict[str, Any] | None:
    """
    Attempts to scrape a website using Playwright for JavaScript rendering.
    Returns HTML content string or None if Playwright is unavailable/fails.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.debug("Playwright not installed in environment. Falling back to HTTP parsing.")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            if not response or response.status >= 400:
                await browser.close()
                return None

            html_content = await page.content()
            await browser.close()
            return {"html": html_content, "status_code": response.status}
    except Exception as exc:
        logger.warning("Playwright scraping failed for URL %s: %s", url, str(exc))
        return None
