from app.services.website_scraping.extractors import extract_business_info_from_json_ld
from app.services.website_scraping.html_parser import parse_html_content


def extract_business_description(
    html_content: str, json_ld_list: list[dict] | None = None
) -> str | None:
    """
    Extracts the primary business description in priority order:
    1. Structured JSON-LD description
    2. Meta description / OpenGraph description
    3. About page text section
    4. First meaningful visible paragraph (>= 20 chars)

    Anti-hallucination: Returns None if no reliable description is present.
    """
    # 1. JSON-LD Structured Data
    if json_ld_list:
        json_ld_info = extract_business_info_from_json_ld(json_ld_list)
        if json_ld_info.get("description"):
            desc = json_ld_info["description"].strip()
            if len(desc) >= 10:
                return desc

    # 2. Meta Tags & HTML Content
    parser = parse_html_content(html_content)
    meta_tags = parser.meta_tags

    meta_desc = meta_tags.get("description") or meta_tags.get("og:description")
    if meta_desc and len(meta_desc.strip()) >= 10:
        return meta_desc.strip()

    # 3. Paragraphs fallback
    for paragraph in parser.paragraphs:
        p_clean = paragraph.strip()
        if len(p_clean) >= 20 and not p_clean.startswith("Copyright"):
            return p_clean

    return None
