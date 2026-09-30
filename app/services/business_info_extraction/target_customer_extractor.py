import re
from app.services.website_scraping.html_parser import parse_html_content


TARGET_PATTERNS = [
    r"(?:we\s+(?:serve|provide\s+services\s+for|work\s+with|help|cater\s+to))\s+([^.,;\n]+)",
    r"(?:designed\s+for|tailored\s+for|built\s+for|ideal\s+for)\s+([^.,;\n]+)",
    r"(?:our\s+target\s+(?:customers|audience|clients)\s+(?:are|include))\s+([^.,;\n]+)",
]


def extract_target_customers(html_content: str) -> list[str]:
    """
    Extracts target customer demographics or audience segments ONLY when explicitly stated.

    Returns list of target customer strings or empty list [].
    Does NOT infer target customers solely from business name or category.
    """
    if not html_content:
        return []

    parser = parse_html_content(html_content)
    all_text_blocks = parser.paragraphs + parser.headings

    extracted_targets = []
    seen = set()

    for text in all_text_blocks:
        text_clean = text.strip()
        for pattern in TARGET_PATTERNS:
            match = re.search(pattern, text_clean, re.IGNORECASE)
            if match:
                target_phrase = match.group(1).strip()
                # Clean and split if comma separated
                phrases = [p.strip() for p in re.split(r",| and ", target_phrase) if len(p.strip()) >= 3]
                for p in phrases:
                    p_lower = p.lower()
                    if p_lower not in seen and len(p_lower) <= 60:
                        seen.add(p_lower)
                        extracted_targets.append(p.strip())

    return extracted_targets
