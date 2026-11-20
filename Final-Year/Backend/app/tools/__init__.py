"""LeadSutra AI tool registry."""
from importlib import import_module

_EXPORTS = {
    "adapt_lead": "lead_adapter",
    "extract_emails_from_text": "extract_contacts",
    "extract_phones_from_text": "extract_contacts",
    "score_lead_data": "score_lead",
    "scrape_website": "scrape_site",
    "search_places": "search_places",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module_name}"), name)
