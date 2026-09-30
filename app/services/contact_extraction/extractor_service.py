import logging
from typing import List
from app.models.lead import BusinessLead
from app.services.contact_extraction.contact_info_extractor import (
    extract_all_contact_and_business_info,
)
from app.services.website_scraping.scraper import WebsiteScraper

logger = logging.getLogger(__name__)


class ContactExtractionService:
    """Service that executes contact and business information extraction on LeadSutra leads."""

    def __init__(self, scraper: WebsiteScraper | None = None) -> None:
        self.scraper = scraper or WebsiteScraper()

    async def extract_lead_contact_info(self, lead: BusinessLead) -> BusinessLead:
        """
        Extracts contact details (emails, phones, contact person, contact page, operating hours)
        from a business website and merges them into the BusinessLead instance.

        Non-destructive:
        - Does NOT overwrite existing provider data (e.g. Google/Foursquare phone numbers).
        - Handles missing/inaccessible websites gracefully without throwing exceptions.
        """
        if not lead.website:
            lead_dict = lead.model_dump()
            lead_dict["contact_extraction_status"] = "skipped"
            lead_dict["extraction_metadata"] = {
                "contact_extraction_status": "skipped",
                "reason": "no_website",
            }
            return BusinessLead(**lead_dict)

        # Scrape website HTML using WebsiteScraper
        scrape_result = await self.scraper.scrape_website(lead.website, check_internal_pages=True)

        if not scrape_result.get("website_accessible"):
            lead_dict = lead.model_dump()
            status_code = scrape_result.get("scrape_status", "failed")
            lead_dict["contact_extraction_status"] = "failed"
            lead_dict["extraction_metadata"] = {
                "contact_extraction_status": "failed",
                "reason": scrape_result.get("scrape_error") or status_code,
            }
            return BusinessLead(**lead_dict)

        # Extract contact and business info
        url = scrape_result.get("website") or lead.website
        scraped_data = scrape_result.get("scraped_data", {})
        
        # Build HTML content from scraper or run extractor
        # Fetch homepage HTML for contact extraction
        try:
            import httpx
            from app.services.website_scraping.website_detector import DEFAULT_USER_AGENT

            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, verify=False) as client:
                res = await client.get(url, headers={"User-Agent": DEFAULT_USER_AGENT})
                html_content = res.text if res.status_code == 200 else ""
        except Exception:
            html_content = ""

        extracted = extract_all_contact_and_business_info(html_content, url)

        lead_dict = lead.model_dump()
        lead_dict["contact_extraction_status"] = "success"

        # Non-destructive merging logic
        # 1. Email: fill if lead lacks email
        if extracted.get("primary_email") and not lead_dict.get("email"):
            lead_dict["email"] = extracted["primary_email"]

        if extracted.get("contact_emails"):
            existing_emails = set(lead_dict.get("contact_emails") or [])
            if lead_dict.get("email"):
                existing_emails.add(lead_dict["email"])
            for e in extracted["contact_emails"]:
                existing_emails.add(e)
            lead_dict["contact_emails"] = list(existing_emails)

        # 2. Phone: Fill phone ONLY if lead lacks it (preserve Google/Foursquare verified phone)
        if extracted.get("primary_phone") and not lead_dict.get("phone"):
            lead_dict["phone"] = extracted["primary_phone"]

        # 3. Contact person
        if extracted.get("contact_person") and not lead_dict.get("contact_person"):
            lead_dict["contact_person"] = extracted["contact_person"]

        # 4. URLs
        if extracted.get("contact_page_url") and not lead_dict.get("contact_page_url"):
            lead_dict["contact_page_url"] = extracted["contact_page_url"]

        if extracted.get("about_page_url") and not lead_dict.get("about_page_url"):
            lead_dict["about_page_url"] = extracted["about_page_url"]

        # 5. Operating hours
        if extracted.get("operating_hours") and not lead_dict.get("operating_hours"):
            lead_dict["operating_hours"] = extracted["operating_hours"]

        # 6. Social links & Services
        if extracted.get("social_links"):
            existing_socials = lead_dict.get("social_links") or {}
            lead_dict["social_links"] = {**extracted["social_links"], **existing_socials}

        if extracted.get("services"):
            existing_svcs = set(lead_dict.get("services") or [])
            for s in extracted["services"]:
                existing_svcs.add(s)
            lead_dict["services"] = list(existing_svcs)

        if extracted.get("description") and not lead_dict.get("description"):
            lead_dict["description"] = extracted["description"]

        # 7. Provenance & Metadata
        lead_dict["extraction_metadata"] = extracted.get("extraction_metadata", {})

        return BusinessLead(**lead_dict)

    async def extract_leads_contact_info(
        self, leads: List[BusinessLead]
    ) -> List[BusinessLead]:
        """Processes a list of leads, extracting contact information for each."""
        processed: List[BusinessLead] = []
        for lead in leads:
            try:
                enriched = await self.extract_lead_contact_info(lead)
                processed.append(enriched)
            except Exception as exc:
                logger.error("Failed contact extraction for %s: %s", lead.name, str(exc))
                lead_dict = lead.model_dump()
                lead_dict["contact_extraction_status"] = "failed"
                processed.append(BusinessLead(**lead_dict))
        return processed


# Convenience functions
async def extract_lead_contact_info(lead: BusinessLead) -> BusinessLead:
    service = ContactExtractionService()
    return await service.extract_lead_contact_info(lead)


async def extract_leads_contact_info(leads: List[BusinessLead]) -> List[BusinessLead]:
    service = ContactExtractionService()
    return await service.extract_leads_contact_info(leads)
