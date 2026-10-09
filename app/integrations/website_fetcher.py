"""Website crawling migrated from the original enrichment module."""
from __future__ import annotations

import httpx
import asyncio
import logging
import re
from bs4 import BeautifulSoup, Tag
from collections import OrderedDict, defaultdict, deque
from collections.abc import Iterable
from playwright.async_api import Error as PlaywrightError
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse
from app.integrations.maps_scraper import BrowserConfig, BrowserManager
from app.agents.lead_pipeline.schemas import BusinessRecord
from app.agents.lead_pipeline.schemas import (
    WebsiteStatus,
    CrawlError,
    WebsiteLink,
    WebsitePage,
    WebsiteCrawlResult,
    WebsiteCrawlerConfig,
)
from app.utils.safe_http import PublicTransport, WebsiteFetchError, bounded_get

logger = logging.getLogger(__name__)

SOCIAL_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com",
    "tiktok.com", "youtube.com", "youtu.be", "pinterest.com", "reddit.com",
}
DIRECTORY_HOSTS = {
    "yelp.com", "yellowpages.com", "tripadvisor.com", "foursquare.com",
    "google.com", "maps.google.com", "justdial.com", "indiamart.com",
}
SKIP_PATH = re.compile(r"/(?:login|signin|sign-in|cart|checkout|basket|account|wp-admin)(?:/|$)", re.I)
SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4", ".mp3")
PAGE_HINTS = {
    "about": ("about", "company", "story"),
    "services": ("service", "what-we-do", "solutions"),
    "products": ("product", "shop", "catalog"),
    "contact": ("contact", "location", "reach-us", "reach-out", "get-in-touch", "getintouch", "contactus"),
    "team": ("team", "people", "staff"),
    "faq": ("faq", "frequently-asked", "help"),
}







def normalize_url(value: str | None, *, preserve_path: bool = False) -> str | None:
    """Normalize only structurally valid HTTP(S) website URLs."""
    if not value or not value.strip():
        return None
    candidate = value.strip()
    if not re.match(r"^https?://", candidate, re.I):
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if any(ch.isspace() for ch in parsed.netloc) or not parsed.hostname or "." not in parsed.hostname:
            return None
        # Accessing .port also validates malformed port syntax.
        _ = parsed.port
        host = parsed.hostname.lower().encode("idna").decode("ascii")
        netloc = host + (f":{parsed.port}" if parsed.port else "")
        path = parsed.path or "/"
        if path != "/" and not preserve_path:
            path = path.rstrip("/")
        tracking = {"gclid", "fbclid", "dclid", "msclkid"}
        query_items = [
            (key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in tracking
        ]
        query = urlencode(sorted(query_items))
        return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))
    except (ValueError, UnicodeError):
        return None

def _host_is_excluded(host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == excluded or host.endswith("." + excluded) for excluded in SOCIAL_HOSTS | DIRECTORY_HOSTS)

def _page_type(url: str, title: str | None, text: str) -> str:
    haystack = f"{url} {title or ''}".lower()
    for kind, terms in PAGE_HINTS.items():
        if any(term in haystack for term in terms):
            return kind
    return "home" if urlparse(url).path in {"", "/"} else "other"

def _clean_page(html: str, page_url: str) -> tuple[WebsitePage, list[tuple[str, str]]]:
    html = html if isinstance(html, str) else ""
    soup = BeautifulSoup(html, "html.parser")
    outgoing: list[WebsiteLink] = []
    for anchor in soup.find_all("a", href=True):
        suspicious_context = False
        for ancestor in (anchor, *anchor.parents):
            if not isinstance(ancestor, Tag):
                continue
            attrs = ancestor.attrs if isinstance(ancestor.attrs, dict) else {}
            marker = " ".join([
                str(attrs.get("id") or ""),
                " ".join(str(item) for item in (attrs.get("class") or [])),
            ]).casefold()
            if any(term in marker for term in (
                "cookie", "consent", "tracking", "breadcrumb", "social-share", "share-button",
                "share-buttons", "comment", "advert", "ad-container", "embed", "widget",
            )):
                suspicious_context = True
                break
        if suspicious_context:
            continue
        raw_href = anchor.get("href")
        if not isinstance(raw_href, str) or not raw_href.strip():
            continue
        raw_href = raw_href.strip()
        target = urljoin(page_url, raw_href)
        scheme = urlparse(target).scheme.lower()
        if scheme in {"http", "https", "mailto", "tel"}:
            outgoing.append(WebsiteLink(url=target, text=" ".join(anchor.stripped_strings) or None))
    signals: list[str] = []
    generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    if generator and generator.get("content"):
        signals.append("meta-generator:" + generator["content"].strip())
    viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    if viewport and isinstance(viewport.get("content"), str):
        signals.append("meta-viewport:" + viewport["content"].strip())
    for script in soup.find_all("script", src=True):
        signals.append("script-src:" + script["src"].strip())
    for stylesheet in soup.find_all("link", rel=re.compile("stylesheet", re.I), href=True):
        signals.append("stylesheet:" + stylesheet["href"].strip())
    for node in [soup.html, soup.body]:
        if node:
            if node.get("id"):
                signals.append("html-id:" + str(node["id"]))
            classes = node.get("class") or []
            if isinstance(classes, str):
                classes = [classes]
            for class_name in classes:
                signals.append("html-class:" + str(class_name))
    if soup.find(id="__NEXT_DATA__") or soup.find(id="__next_data__"):
        signals.append("dom-signature:__next_data__")
    if soup.find(attrs={"data-reactroot": True}):
        signals.append("dom-signature:data-reactroot")
    if any("shopify-section" in " ".join(str(value) for value in (node.get("class") or [])).casefold()
           for node in soup.find_all(True)):
        signals.append("dom-signature:shopify-section")
    contact_chunks: list[str] = []
    seen_contact_chunks: set[str] = set()
    for node in soup.find_all(["footer", "address"]):
        if node.find_parent(["script", "style", "noscript"]):
            continue
        if node.has_attr("hidden") or str(node.get("aria-hidden", "")).lower() == "true":
            continue
        if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", str(node.get("style", "")), re.I):
            continue
        text = " ".join(node.stripped_strings)
        key = re.sub(r"\s+", " ", text).casefold().strip()
        if key and key not in seen_contact_chunks:
            seen_contact_chunks.add(key)
            contact_chunks.append(text)
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else None
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description_value = meta.get("content") if meta else None
    description = description_value.strip() if isinstance(description_value, str) else None

    for node in soup.select("script, style, noscript, svg, iframe, canvas, form, nav, footer, header, aside"):
        node.decompose()
    for node in list(soup.find_all(True)):
        # Removing a noisy ancestor also decomposes its descendants. BeautifulSoup
        # leaves those saved Tag objects in this snapshot with attrs=None, and
        # Tag.get() then raises AttributeError instead of returning a default.
        if not isinstance(node.attrs, dict):
            continue
        node_id = node.get("id") or ""
        node_classes = node.get("class") or []
        if isinstance(node_classes, str):
            node_classes = [node_classes]
        marker = " ".join([str(node_id), " ".join(str(value) for value in node_classes)]).lower()
        if any(term in marker for term in ("cookie", "consent", "tracking", "breadcrumb", "social-share")):
            node.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    chunks: list[str] = []
    seen: set[str] = set()
    for node in root.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
        content = " ".join(node.stripped_strings)
        normalized = re.sub(r"\s+", " ", content).strip()
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            chunks.append(normalized)
    text = "\n".join(chunks)
    if not text:
        text = re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()

    links: list[tuple[str, str]] = []
    for link in outgoing:
        if urlparse(link.url).scheme not in {"http", "https"}:
            continue
        target = normalize_url(link.url)
        if target:
            links.append((target, link.text or ""))
    return WebsitePage(
        page_url=page_url, page_title=title or None, meta_description=description or None,
        main_text=text, contact_text="\n".join(contact_chunks), page_type=_page_type(page_url, title, text),
        extraction_status="success" if text else "empty",
        outgoing_links=outgoing, technology_signals=list(dict.fromkeys(signals)),
    ), links

def _link_priority(url: str, label: str) -> int:
    haystack = (url + " " + label).lower()
    for priority, kind in enumerate(("about", "services", "products", "contact", "team", "faq")):
        if any(term in haystack for term in PAGE_HINTS[kind]):
            return priority
    return 99

class WebsiteCrawler:
    """Discover and boundedly crawl one business's candidate official website."""

    def __init__(
        self,
        config: WebsiteCrawlerConfig | None = None,
        browser_config: BrowserConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        browser_manager_factory: Any = BrowserManager,
    ) -> None:
        self.config = config or WebsiteCrawlerConfig()
        self.browser_config = browser_config or BrowserConfig()
        self.client = client
        self.browser_manager_factory = browser_manager_factory

    async def crawl(self, business: BusinessRecord) -> WebsiteCrawlResult:
        raw = business.website
        base = normalize_url(raw)
        if not raw:
            return WebsiteCrawlResult(lead_id=business.lead_id, website_status=WebsiteStatus.NOT_FOUND)
        if not base:
            return WebsiteCrawlResult(lead_id=business.lead_id, website_status=WebsiteStatus.INVALID_URL)
        host = urlparse(base).hostname or ""
        if _host_is_excluded(host):
            return WebsiteCrawlResult(lead_id=business.lead_id, website_status=WebsiteStatus.UNCERTAIN, website_url=base,
                                      crawl_errors=[CrawlError(url=base, message="Candidate is a social or directory page, not an official website")])

        own_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds), follow_redirects=False,
            transport=PublicTransport(), trust_env=False,
            headers={"User-Agent": self.config.user_agent},
        )
        result = WebsiteCrawlResult(lead_id=business.lead_id, website_status=WebsiteStatus.UNREACHABLE, website_url=base)
        visited: set[str] = set()
        queue: deque[str] = deque([base])
        queued: set[str] = {base}
        try:
            async with asyncio.timeout(self.config.crawl_timeout_seconds):
                return await self._crawl_pages(client, host, result, visited, queue, queued)
        except TimeoutError:
            result.crawl_errors.append(CrawlError(message="Website crawl deadline exceeded; keeping partial data"))
            if result.website_content:
                result.website_status = WebsiteStatus.ACTIVE
            return result
        finally:
            result.field_sources = {
                "website_content": [page.page_url for page in result.website_content],
                "about": [entry["source_url"] for entry in result.about],
                "services": [entry["source_url"] for entry in result.services],
                "contact_page_url": [result.contact_page_url] if result.contact_page_url else [],
            }
            if own_client:
                await client.aclose()

    async def _crawl_pages(self, client, host, result, visited, queue, queued):
        browser_manager = None
        try:
            while queue and len(visited) < self.config.max_pages:
                url = queue.popleft()
                if url in visited:
                    continue
                visited.add(url)
                result.pages_visited.append(url)
                try:
                    response = await self._fetch(client, url, host)
                    if response is None:
                        result.crawl_errors.append(CrawlError(url=url, message="HTTP client returned no response"))
                        continue
                    response.raise_for_status()
                    final_url = normalize_url(str(response.url), preserve_path=True)
                    if not final_url:
                        result.crawl_errors.append(CrawlError(url=url, message="Redirected to an invalid URL"))
                        continue
                    final_host = urlparse(final_url).hostname or ""
                    if _host_is_excluded(final_host) or not _same_site(host, final_host):
                        result.website_status = WebsiteStatus.UNCERTAIN
                        result.crawl_errors.append(CrawlError(url=url, message="Website redirected outside the candidate site"))
                        break
                    if response.status_code == 404:
                        result.crawl_errors.append(CrawlError(url=final_url, message="HTTP 404"))
                        continue
                    response_headers = getattr(response, "headers", None) or {}
                    content_type = str(response_headers.get("content-type", "")).lower()
                    if "html" not in content_type and content_type:
                        result.crawl_errors.append(CrawlError(url=final_url, message=f"Unsupported content type: {content_type}"))
                        continue
                    page, links = _clean_page(response.text, final_url)
                    page.response_headers = {
                        key.lower(): value for key, value in response_headers.items()
                        if key.lower() in {"server", "x-powered-by", "x-generator", "x-shopify-stage"}
                    }
                    page.technology_signals.extend(
                        f"header:{key}:{value}" for key, value in page.response_headers.items()
                    )
                    if len(page.main_text) < self.config.min_text_for_static and "<script" in response.text.lower():
                        try:
                            if browser_manager is None:
                                browser_manager = self.browser_manager_factory(self.browser_config)
                                await browser_manager.start()
                                if isinstance(browser_manager, BrowserManager):
                                    await self._guard_browser(browser_manager, client, host, result)
                            rendered = await self._render_page(final_url, browser_manager)
                        except Exception as exc:
                            rendered = None
                            result.crawl_errors.append(CrawlError(url=final_url, message=f"Browser fallback failed: {type(exc).__name__}: {exc}"))
                            if browser_manager is not None:
                                await browser_manager.close()
                            browser_manager = None
                        if rendered is not None:
                            rendered_page, rendered_links = _clean_page(rendered, final_url)
                            rendered_page.response_headers = page.response_headers
                            rendered_page.technology_signals = list(dict.fromkeys(
                                page.technology_signals + rendered_page.technology_signals
                                + [f"header:{key}:{value}" for key, value in page.response_headers.items()]
                            ))
                            page = rendered_page
                            links = links + rendered_links
                        else:
                            result.crawl_errors.append(CrawlError(url=final_url, message="Playwright rendering failed or timed out"))
                    result.website_content.append(page)
                    if page.page_type == "about" and page.main_text:
                        result.about.append({"text": page.main_text, "source_url": page.page_url})
                    if page.page_type == "services" and page.main_text:
                        result.services.append({"text": page.main_text, "source_url": page.page_url})
                    if page.page_type == "contact":
                        result.contact_page_url = page.page_url
                    priority_links = sorted(links, key=lambda item: _link_priority(*item))
                    for target, _label in priority_links:
                        parsed_target = urlparse(target)
                        if not _same_site(host, parsed_target.hostname or ""):
                            continue
                        if SKIP_PATH.search(parsed_target.path) or parsed_target.path.lower().endswith(SKIP_EXTENSIONS):
                            continue
                        if len(queued) < self.config.max_pages and target not in queued and target not in visited:
                            queued.add(target)
                            queue.append(target)
                except (httpx.HTTPError, httpx.InvalidURL, WebsiteFetchError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
                        if not result.website_content:
                            result.website_status = WebsiteStatus.BLOCKED
                    message = (f"HTTP {exc.response.status_code}: website request failed"
                               if isinstance(exc, httpx.HTTPStatusError) else f"{type(exc).__name__}: {exc}")
                    result.crawl_errors.append(CrawlError(url=url, message=" ".join(message.split())))
                except Exception as exc:
                    logger.exception("Website crawl failed for %s", url)
                    result.crawl_errors.append(CrawlError(url=url, message=f"{type(exc).__name__}: {exc}"))
            if result.website_content and result.website_status != WebsiteStatus.UNCERTAIN:
                result.website_status = WebsiteStatus.ACTIVE
            elif result.website_status == WebsiteStatus.UNREACHABLE and result.crawl_errors and "404" in result.crawl_errors[0].message:
                result.website_status = WebsiteStatus.UNREACHABLE
            return result
        finally:
            if browser_manager is not None:
                await browser_manager.close()

    async def _fetch(self, client, url, host):
        seen = set()
        for _ in range(6):
            if url in seen:
                raise WebsiteFetchError("Website redirect loop detected")
            seen.add(url)
            if host is not None and not _same_site(host, urlparse(url).hostname or ""):
                raise WebsiteFetchError("Blocked redirect outside the candidate site")
            response = (await bounded_get(client, url, self.config.max_response_bytes)
                        if isinstance(client, httpx.AsyncClient) else await client.get(url))
            if response is None or response.status_code not in {301, 302, 303, 307, 308}:
                return response
            url = normalize_url(urljoin(url, response.headers.get("location", "")), preserve_path=True)
            if not url:
                raise WebsiteFetchError("Invalid website redirect")
        raise WebsiteFetchError("Too many website redirects")

    async def _guard_browser(self, manager, client, host, result):
        requests = 0

        async def route_request(route):
            nonlocal requests
            requests += 1
            request = route.request
            if (requests > 40 or request.method != "GET"
                    or request.resource_type in {"image", "media", "font"}
                    or (request.is_navigation_request() and not _same_site(host, urlparse(request.url).hostname or ""))):
                await route.abort()
                return
            try:
                response = await self._fetch(client, request.url, host if request.is_navigation_request() else None)
                await route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
            except Exception as exc:
                result.crawl_errors.append(CrawlError(url=request.url, message=f"Browser resource failed: {type(exc).__name__}: {exc}"))
                logger.warning("Browser resource blocked or failed: %s", type(exc).__name__)
                await route.abort()

        await manager.context.route("**/*", route_request)
        await manager.context.route_web_socket("**/*", lambda socket: socket.close())

    async def _render_page(self, url: str, manager: Any) -> str | None:
        try:
            await manager.page.goto(url, wait_until="domcontentloaded")
            return await manager.page.content()
        except PlaywrightError as exc:
            logger.debug("Browser rendering failed for %s: %s", url, exc)
            return None

def _same_site(original_host: str, candidate_host: str) -> bool:
    original = original_host.lower().removeprefix("www.")
    candidate = candidate_host.lower().removeprefix("www.")
    return original == candidate

async def crawl_business_website(
    business: BusinessRecord,
    *,
    config: WebsiteCrawlerConfig | None = None,
    browser_config: BrowserConfig | None = None,
) -> WebsiteCrawlResult:
    """Convenience function for a single Part 1 business record."""
    return await WebsiteCrawler(config=config, browser_config=browser_config).crawl(business)
