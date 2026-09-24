import logging
from typing import List, Tuple
from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead
from app.services.business_info_extraction.description_extractor import (
    extract_business_description,
)
from app.services.business_info_extraction.services_products_extractor import (
    extract_services_and_products,
)
from app.services.business_info_extraction.target_customer_extractor import (
    extract_target_customers,
)
from app.services.website_scraping.html_parser import extract_json_ld, parse_html_content
from app.services.website_scraping.scraper import WebsiteScraper

logger = logging.getLogger(__name__)


class BusinessProfileExtractionService:
    """Orchestrates structured BusinessProfile creation from discovered BusinessLead objects."""

    def __init__(self, scraper: WebsiteScraper | None = None) -> None:
        self.scraper = scraper or WebsiteScraper()

    async def build_business_profile(
        self, lead: BusinessLead, html_content: str = ""
    ) -> BusinessProfile:
        """
        Builds a BusinessProfile model by merging provider discovery data,
        scraped website details, and contact extraction results.
        """
        # If html_content is empty and lead has a website, fetch HTML if accessible
        json_ld_list: list[dict] = []
        if not html_content and lead.website:
            try:
                scrape_res = await self.scraper.scrape_website(lead.website, check_internal_pages=False)
                if scrape_res.get("website_accessible"):
                    import httpx
                    from app.services.website_scraping.website_detector import DEFAULT_USER_AGENT

                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, verify=False) as client:
                        res = await client.get(lead.website, headers={"User-Agent": DEFAULT_USER_AGENT})
                        if res.status_code == 200:
                            html_content = res.text
            except Exception as exc:
                logger.warning("Could not fetch HTML for profile extraction on %s: %s", lead.name, str(exc))

        if html_content:
            json_ld_list = extract_json_ld(html_content)

        # 1. Description
        description = extract_business_description(html_content, json_ld_list) or lead.description

        # 2. Services & Products
        services_extracted, products_extracted = extract_services_and_products(html_content, json_ld_list)
        all_services = list(set((lead.services or []) + services_extracted))

        # 3. Target Customers
        target_customers = extract_target_customers(html_content)

        # 4. Sub-category extraction
        sub_category = None
        if json_ld_list:
            for obj in json_ld_list:
                if isinstance(obj, dict) and obj.get("@type"):
                    t = str(obj["@type"])
                    if t.lower() not in ("localbusiness", "organization"):
                        sub_category = t
                        break

        # 5. About Info
        about_info = None
        if html_content:
            parser = parse_html_content(html_content)
            for p in parser.paragraphs:
                p_clean = p.strip()
                if len(p_clean) >= 40 and not p_clean.startswith("Copyright"):
                    about_info = p_clean
                    break

        # 6. Online Presence Summary
        online_presence = {
            "website_available": bool(lead.website),
            "website_status": lead.website_status or ("accessible" if lead.website else "no_website"),
            "social_platforms_count": len(lead.social_links or {}),
            "social_platforms": list((lead.social_links or {}).keys()),
        }

        extraction_status = "success"
        if not lead.website:
            extraction_status = "skipped"
        elif not html_content:
            extraction_status = "partial"

        return BusinessProfile(
            lead_id=lead.external_place_id or f"lead_{hash(lead.name)}",
            external_place_id=lead.external_place_id,
            source=lead.source,
            business_name=lead.name,
            category=lead.category,
            sub_category=sub_category,
            description=description,
            services=all_services,
            products=products_extracted,
            target_customers=target_customers,
            about_info=about_info,
            address=lead.address,
            phone=lead.phone,
            email=lead.email,
            website=lead.website,
            social_links=lead.social_links or {},
            operating_hours=lead.operating_hours,
            online_presence=online_presence,
            profile_extraction_status=extraction_status,
            extraction_source="hybrid" if lead.website else "provider_only",
        )

    async def extract_business_profiles(
        self, leads: List[BusinessLead]
    ) -> Tuple[List[BusinessLead], List[BusinessProfile]]:
        """
        Batch processes a list of BusinessLead instances and generates linked BusinessProfile models.
        Prevents duplicate profile records per lead.
        """
        profiles: List[BusinessProfile] = []
        seen_lead_ids = set()

        for lead in leads:
            lead_identifier = lead.external_place_id or lead.name
            if lead_identifier in seen_lead_ids:
                continue
            seen_lead_ids.add(lead_identifier)

            try:
                profile = await self.build_business_profile(lead)
                profiles.append(profile)
            except Exception as exc:
                logger.error("Failed profile creation for %s: %s", lead.name, str(exc))
                # Fallback minimal profile
                profiles.append(
                    BusinessProfile(
                        lead_id=lead.external_place_id or f"lead_{hash(lead.name)}",
                        external_place_id=lead.external_place_id,
                        source=lead.source,
                        business_name=lead.name,
                        category=lead.category,
                        address=lead.address,
                        phone=lead.phone,
                        email=lead.email,
                        website=lead.website,
                        profile_extraction_status="failed",
                        extraction_source="provider_only",
                    )
                )

        return leads, profiles


# Convenience function
async def extract_business_profiles(
    leads: List[BusinessLead]
) -> Tuple[List[BusinessLead], List[BusinessProfile]]:
    service = BusinessProfileExtractionService()
    return await service.extract_business_profiles(leads)
