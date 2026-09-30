import re
from typing import Tuple
from app.services.website_scraping.html_parser import parse_html_content

NAV_KEYWORDS = {
    "home",
    "about",
    "contact",
    "blog",
    "privacy policy",
    "terms",
    "login",
    "register",
    "cart",
    "checkout",
}


def extract_services_and_products(
    html_content: str, json_ld_list: list[dict] | None = None
) -> Tuple[list[str], list[str]]:
    """
    Extracts explicit services and products offered by the business.

    Returns:
        (services: list[str], products: list[str])
    """
    services: list[str] = []
    products: list[str] = []
    seen_services = set()
    seen_products = set()

    # 1. JSON-LD Extraction
    if json_ld_list:
        for obj in json_ld_list:
            if isinstance(obj, dict):
                obj_type = str(obj.get("@type", "")).lower()

                # Product schema
                if "product" in obj_type and obj.get("name"):
                    p_name = str(obj["name"]).strip()
                    if p_name and p_name not in seen_products:
                        seen_products.add(p_name)
                        products.append(p_name)

                # Service schema / offers
                if "service" in obj_type and obj.get("name"):
                    s_name = str(obj["name"]).strip()
                    if s_name and s_name not in seen_services:
                        seen_services.add(s_name)
                        services.append(s_name)

                # offers / makesOffer / knowsAbout
                for key in ("makesOffer", "knowsAbout", "hasOfferCatalog", "services"):
                    val = obj.get(key)
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, str):
                                item_clean = item.strip()
                                if item_clean and item_clean not in seen_services:
                                    seen_services.add(item_clean)
                                    services.append(item_clean)
                            elif isinstance(item, dict) and item.get("name"):
                                item_name = str(item["name"]).strip()
                                if item_name and item_name not in seen_services:
                                    seen_services.add(item_name)
                                    services.append(item_name)

    # 2. HTML Heading & Paragraph Parsing
    parser = parse_html_content(html_content)

    # Extract services from HTML heading sections (e.g. "Services: Web Dev, SEO, Consulting")
    for heading in parser.headings:
        if re.search(r"\b(service|services|solutions|what we do)\b", heading, re.IGNORECASE):
            # Check paragraphs right after
            for p in parser.paragraphs:
                p_clean = p.strip()
                if len(p_clean) < 80 and not any(nk in p_clean.lower() for nk in NAV_KEYWORDS):
                    # Comma separated or bullet point items
                    items = [it.strip() for it in re.split(r"[,•|\n]", p_clean) if len(it.strip()) >= 3]
                    for item in items:
                        if item.lower() not in NAV_KEYWORDS and item not in seen_services:
                            seen_services.add(item)
                            services.append(item)

        if re.search(r"\b(product|products|our products|catalog)\b", heading, re.IGNORECASE):
            for p in parser.paragraphs:
                p_clean = p.strip()
                if len(p_clean) < 80 and not any(nk in p_clean.lower() for nk in NAV_KEYWORDS):
                    items = [it.strip() for it in re.split(r"[,•|\n]", p_clean) if len(it.strip()) >= 3]
                    for item in items:
                        if item.lower() not in NAV_KEYWORDS and item not in seen_products:
                            seen_products.add(item)
                            products.append(item)

    return services, products
