import html
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlparse


class SocialLinkParser(HTMLParser):
    """HTML parser to collect anchor hrefs, meta tags, titles, headings, and JSON-LD scripts."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.meta_tags: dict[str, str] = {}
        self.json_ld_scripts: list[str] = []
        self.title: str = ""
        self.headings: list[str] = []
        self.paragraphs: list[str] = []

        self._in_title = False
        self._in_heading = False
        self._in_p = False
        self._in_script_jsonld = False
        self._current_text = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag == "a":
            href = attr_dict.get("href")
            if href:
                self.hrefs.append(href)
        elif tag == "meta":
            key = attr_dict.get("name") or attr_dict.get("property")
            content = attr_dict.get("content")
            if key and content:
                self.meta_tags[key.lower()] = content.strip()
        elif tag == "title":
            self._in_title = True
            self._current_text = []
        elif tag in ("h1", "h2", "h3"):
            self._in_heading = True
            self._current_text = []
        elif tag == "p":
            self._in_p = True
            self._current_text = []
        elif tag == "script" and attr_dict.get("type") == "application/ld+json":
            self._in_script_jsonld = True
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        text = "".join(self._current_text).strip()
        if tag == "title" and self._in_title:
            self.title = text
            self._in_title = False
        elif tag in ("h1", "h2", "h3") and self._in_heading:
            if text:
                self.headings.append(text)
            self._in_heading = False
        elif tag == "p" and self._in_p:
            if text:
                self.paragraphs.append(text)
            self._in_p = False
        elif tag == "script" and self._in_script_jsonld:
            if text:
                self.json_ld_scripts.append(text)
            self._in_script_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_title or self._in_heading or self._in_p or self._in_script_jsonld:
            self._current_text.append(data)


def parse_html_content(html_str: str) -> SocialLinkParser:
    """Parses raw HTML string into structured SocialLinkParser data."""
    parser = SocialLinkParser()
    try:
        parser.feed(html_str)
    except Exception:
        pass
    return parser


def extract_json_ld(html_str: str) -> list[dict]:
    """Extracts and parses all JSON-LD data structures from HTML."""
    parser = parse_html_content(html_str)
    json_objects = []

    # Direct parser extraction
    for script_text in parser.json_ld_scripts:
        try:
            data = json.loads(script_text)
            if isinstance(data, dict):
                json_objects.append(data)
            elif isinstance(data, list):
                json_objects.extend([item for item in data if isinstance(item, dict)])
        except Exception:
            continue

    # Regex fallback for embedded script blocks
    if not json_objects:
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(pattern, html_str, re.DOTALL | re.IGNORECASE)
        for match in matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, dict):
                    json_objects.append(data)
                elif isinstance(data, list):
                    json_objects.extend([item for item in data if isinstance(item, dict)])
            except Exception:
                continue

    return json_objects


def extract_social_links(html_str: str) -> dict[str, str]:
    """
    Extracts social media profile links present in HTML anchor tags.
    Supports: instagram, facebook, linkedin, twitter/x, youtube.
    """
    parser = parse_html_content(html_str)
    social_links: dict[str, str] = {}

    patterns = {
        "instagram": r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.-]+/?",
        "facebook": r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9_.-]+/?",
        "linkedin": r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_.-]+/?",
        "twitter": r"https?://(?:www\.)?(?:twitter\.com|x\.com)/[A-Za-z0-9_.-]+/?",
        "youtube": r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)?[A-Za-z0-9_.-]+/?",
    }

    # Search extracted hrefs
    for href in parser.hrefs:
        for platform, regex in patterns.items():
            if platform not in social_links and re.match(regex, href, re.IGNORECASE):
                # Clean URL (strip tracking params if needed)
                clean_url = href.split("?")[0]
                social_links[platform] = clean_url

    # Regex search over raw HTML as fallback
    if len(social_links) < len(patterns):
        for platform, regex in patterns.items():
            if platform not in social_links:
                match = re.search(regex, html_str, re.IGNORECASE)
                if match:
                    social_links[platform] = match.group(0).split("?")[0]

    return social_links


def extract_relevant_internal_links(html_str: str, base_url: str) -> list[str]:
    """
    Finds relevant internal page links (about, contact, services, products, company).
    Does NOT crawl external websites.
    """
    parser = parse_html_content(html_str)
    base_netloc = urlparse(base_url).netloc.lower()
    target_keywords = ("about", "contact", "service", "product", "company")

    relevant_links = []
    seen = set()

    for href in parser.hrefs:
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Ensure same origin
        if parsed.netloc.lower() == base_netloc and parsed.scheme in ("http", "https"):
            path = parsed.path.lower()
            if any(kw in path for kw in target_keywords):
                clean_link = full_url.split("#")[0].split("?")[0].rstrip("/")
                if clean_link not in seen and clean_link != base_url.rstrip("/"):
                    seen.add(clean_link)
                    relevant_links.append(clean_link)

    return relevant_links[:5]  # Limit to 5 relevant page links max
