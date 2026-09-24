import logging
from typing import List
from app.models.lead import BusinessLead
from app.services.website_scraping.scraper import WebsiteScraper
from app.services.website_scraping.url_validator import validate_and_normalize_url

logger = logging.getLogger(__name__)


class WebsiteEnrichmentService:
    """Enriches BusinessLead instances with website scraping metadata and extracted business details."""

    def __init__(self, scraper: WebsiteScraper | None = None) -> None:
        self.scraper = scraper or WebsiteScraper()

    async def enrich_lead(
        self, lead: BusinessLead, check_internal_pages: bool = True
    ) -> BusinessLead:
        """
        Enriches a single BusinessLead with website scraping data.
        Non-destructive: NEVER overwrites existing non-null provider fields (phone, address, name).
        """
        if not lead.website:
            lead_dict = lead.model_dump()
            lead_dict["website_status"] = "no_website"
            lead_dict["scrape_status"] = "no_website"
            return BusinessLead(**lead_dict)

        # Validate URL syntax first
        is_valid, normalized_url, url_status = validate_and_normalize_url(lead.website)

        if not is_valid:
            lead_dict = lead.model_dump()
            lead_dict["website_status"] = url_status  # "invalid_url"
            lead_dict["scrape_status"] = "failed"
            return BusinessLead(**lead_dict)

        # Scrape website safely
        result = await self.scraper.scrape_website(
            normalized_url, check_internal_pages=check_internal_pages
        )

        lead_dict = lead.model_dump()
        lead_dict["website"] = normalized_url
        lead_dict["website_status"] = result.get("scrape_status", "unknown")
        lead_dict["scrape_status"] = (
            "success" if result.get("website_accessible") else result.get("scrape_status", "failed")
        )

        scraped_data = result.get("scraped_data", {})

        # Non-destructive enrichments
        if scraped_data.get("description") and not lead_dict.get("description"):
            lead_dict["description"] = scraped_data["description"]

        if scraped_data.get("social_links"):
            existing_socials = lead_dict.get("social_links") or {}
            merged_socials = {**scraped_data["social_links"], **existing_socials}
            lead_dict["social_links"] = merged_socials

        if scraped_data.get("services"):
            existing_svcs = set(lead_dict.get("services") or [])
            for svc in scraped_data["services"]:
                existing_svcs.add(svc)
            lead_dict["services"] = list(existing_svcs)

        # Fill missing contact fields ONLY if lead lacks them
        if scraped_data.get("phone") and not lead_dict.get("phone"):
            lead_dict["phone"] = scraped_data["phone"]

        if scraped_data.get("address") and not lead_dict.get("address"):
            lead_dict["address"] = scraped_data["address"]

        # Store scrape metadata inside raw_data
        raw_meta = dict(lead_dict.get("raw_data") or {})
        raw_meta["website_scrape"] = {
            "scraped_at_url": result.get("website"),
            "website_accessible": result.get("website_accessible"),
            "scrape_status": result.get("scrape_status"),
            "scrape_error": result.get("scrape_error"),
            "meta_description": scraped_data.get("meta_description"),
            "website_title": scraped_data.get("website_title"),
        }
        lead_dict["raw_data"] = raw_meta

        return BusinessLead(**lead_dict)

    async def enrich_leads(
        self, leads: List[BusinessLead], check_internal_pages: bool = True
    ) -> List[BusinessLead]:
        """
        Enriches a batch of BusinessLead instances sequentially or concurrently.
        """
        enriched_list: List[BusinessLead] = []
        for lead in leads:
            try:
                enriched = await self.enrich_lead(lead, check_internal_pages=check_internal_pages)
                enriched_list.append(enriched)
            except Exception as exc:
                logger.error("Error enriching lead %s: %s", lead.name, str(exc))
                enriched_list.append(lead)
        return enriched_list


# Module level convenience functions
async def enrich_lead(lead: BusinessLead) -> BusinessLead:
    """Enrich a single BusinessLead using the default WebsiteEnrichmentService."""
    service = WebsiteEnrichmentService()
    return await service.enrich_lead(lead)


async def enrich_leads(leads: List[BusinessLead]) -> List[BusinessLead]:
    """Enrich a list of BusinessLead instances using default WebsiteEnrichmentService."""
    service = WebsiteEnrichmentService()
    return await service.enrich_leads(leads)
