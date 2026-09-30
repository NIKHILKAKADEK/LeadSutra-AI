from unittest.mock import AsyncMock, patch
import pytest

from app.models.lead import BusinessLead
from app.services.contact_extraction.contact_info_extractor import (
    extract_all_contact_and_business_info,
)
from app.services.contact_extraction.email_extractor import (
    extract_emails,
    validate_and_normalize_email,
)
from app.services.contact_extraction.extractor_service import (
    ContactExtractionService,
    extract_lead_contact_info,
)
from app.services.contact_extraction.person_extractor import extract_contact_person
from app.services.contact_extraction.phone_extractor import extract_phones
from app.services.website_scraping.scraper import WebsiteScraper


class TestEmailExtraction:
    """1-5. Test cases for email extraction, mailto links, syntax validation, and deduplication."""

    def test_email_found_through_mailto_link(self):
        html = '<a href="mailto:contact@leadsutra.ai">Email Us</a>'
        emails = extract_emails(html)
        assert len(emails) == 1
        assert emails[0]["value"] == "contact@leadsutra.ai"
        assert emails[0]["method"] == "mailto"
        assert emails[0]["confidence"] == "high"

    def test_email_found_in_visible_text(self):
        html = "<p>For inquiries, write to support@leadsutra.ai or sales@leadsutra.ai</p>"
        emails = extract_emails(html)
        values = [e["value"] for e in emails]
        assert "support@leadsutra.ai" in values
        assert "sales@leadsutra.ai" in values

    def test_invalid_and_junk_emails_ignored(self):
        assert validate_and_normalize_email("info@example.com") is None  # Dummy domain
        assert validate_and_normalize_email("logo.png@domain.com") is None  # Image filename
        assert validate_and_normalize_email("not-an-email") is None
        assert validate_and_normalize_email("valid@mycompany.co.in") == "valid@mycompany.co.in"

    def test_multiple_emails_extracted(self):
        html = """
        <a href="mailto:info@business.com">Info</a>
        <p>Contact sales@business.com for quotes</p>
        """
        emails = extract_emails(html)
        assert len(emails) == 2
        values = [e["value"] for e in emails]
        assert "info@business.com" in values
        assert "sales@business.com" in values

    def test_duplicate_emails_removed(self):
        html = """
        <a href="mailto:info@business.com">Info 1</a>
        <a href="mailto:info@business.com">Info 2</a>
        <p>Write to info@business.com</p>
        """
        emails = extract_emails(html)
        assert len(emails) == 1
        assert emails[0]["value"] == "info@business.com"


class TestPhoneExtraction:
    """6-8. Test cases for phone extraction and existing phone preservation."""

    def test_phone_extracted_from_tel_link(self):
        html = '<a href="tel:+919876543210">Call Us</a>'
        phones = extract_phones(html)
        assert len(phones) == 1
        assert phones[0]["value"] == "+919876543210"
        assert phones[0]["method"] == "tel_link"

    def test_phone_extracted_from_structured_data(self):
        json_ld = [{"@type": "LocalBusiness", "telephone": "+91 99999 00000"}]
        phones = extract_phones("<html></html>", json_ld_list=json_ld)
        assert len(phones) == 1
        assert phones[0]["value"] == "+919999900000"
        assert phones[0]["method"] == "json_ld"

    @pytest.mark.asyncio
    async def test_existing_phone_preserved_when_scraping_finds_nothing(self):
        lead = BusinessLead(
            name="Apex Clinic",
            phone="+919876543210",
            website="https://apexdental.com",
            source="google",
        )
        mock_scrape_res = {
            "website": "https://apexdental.com",
            "website_available": True,
            "website_accessible": True,
            "scrape_status": "success",
            "scraped_data": {},
        }
        service = ContactExtractionService()
        with patch.object(WebsiteScraper, "scrape_website", return_value=mock_scrape_res):
            with patch("httpx.AsyncClient.get", side_effect=Exception("No connection")):
                enriched = await service.extract_lead_contact_info(lead)
                assert enriched.phone == "+919876543210"  # Original preserved


class TestContactPersonExtraction:
    """9-10. Test cases for contact person extraction."""

    def test_contact_person_found_from_structured_data(self):
        json_ld = [
            {
                "@type": "LocalBusiness",
                "name": "Pawar Tech",
                "founder": {"@type": "Person", "name": "Aditya Pawar"},
            }
        ]
        person = extract_contact_person("<html></html>", json_ld_list=json_ld)
        assert person == "Aditya Pawar"

    def test_contact_person_found_from_about_page_text(self):
        html = "<html><body><h2>Dr. Jatin Shewale - Founder & Lead Dentist</h2></body></html>"
        person = extract_contact_person(html)
        assert person == "Dr. Jatin Shewale"

    def test_contact_person_missing_returns_none(self):
        html = "<html><body><p>Contact our support team at support@company.com</p></body></html>"
        person = extract_contact_person(html)
        assert person is None


class TestBusinessInfoAndJSONLDExtraction:
    """11-15. Test cases for business info, address, social links, JSON-LD, and contact pages."""

    def test_business_description_and_address_extraction(self):
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "Restaurant",
                "name": "Spice Garden",
                "description": "Authentic Maharashtrian cuisine in Nashik.",
                "address": {
                    "streetAddress": "MG Road",
                    "addressLocality": "Nashik"
                }
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        extracted = extract_all_contact_and_business_info(html, "https://spicegarden.com")
        assert extracted["description"] == "Authentic Maharashtrian cuisine in Nashik."
        assert extracted["address"] == "MG Road, Nashik"

    def test_social_profile_extraction(self):
        html = """
        <html>
        <body>
            <a href="https://instagram.com/spicegarden_official">Instagram</a>
            <a href="https://facebook.com/spicegarden">Facebook</a>
        </body>
        </html>
        """
        extracted = extract_all_contact_and_business_info(html, "https://spicegarden.com")
        assert extracted["social_links"]["instagram"] == "https://instagram.com/spicegarden_official"
        assert extracted["social_links"]["facebook"] == "https://facebook.com/spicegarden"

    def test_contact_and_about_page_discovery(self):
        html = """
        <html>
        <body>
            <a href="/contact-us">Contact Us</a>
            <a href="/about-our-company">About Us</a>
        </body>
        </html>
        """
        extracted = extract_all_contact_and_business_info(html, "https://mybiz.com")
        assert extracted["contact_page_url"] == "https://mybiz.com/contact-us"
        assert extracted["about_page_url"] == "https://mybiz.com/about-our-company"


class TestPipelineEdgeCasesAndNonDestructiveMerging:
    """16-20. Test cases for no website, inaccessible website, failure handling, and non-destruction."""

    @pytest.mark.asyncio
    async def test_no_website_handling(self):
        lead = BusinessLead(name="Local Store", website=None)
        service = ContactExtractionService()
        result = await service.extract_lead_contact_info(lead)
        assert result.contact_extraction_status == "skipped"
        assert result.extraction_metadata["reason"] == "no_website"

    @pytest.mark.asyncio
    async def test_website_inaccessible_handling(self):
        lead = BusinessLead(name="Closed Store", website="https://offline-shop.com")
        mock_scrape_res = {
            "website": "https://offline-shop.com",
            "website_available": True,
            "website_accessible": False,
            "scrape_status": "inaccessible",
            "scrape_error": "HTTP status 500",
        }
        service = ContactExtractionService()
        with patch.object(WebsiteScraper, "scrape_website", return_value=mock_scrape_res):
            result = await service.extract_lead_contact_info(lead)
            assert result.contact_extraction_status == "failed"

    @pytest.mark.asyncio
    async def test_scraping_failure_does_not_crash_pipeline(self):
        lead = BusinessLead(name="Faulty Store", website="https://faulty.com")
        service = ContactExtractionService()
        with patch.object(
            WebsiteScraper, "scrape_website", side_effect=Exception("Critical network error")
        ):
            results = await service.extract_leads_contact_info([lead])
            assert len(results) == 1
            assert results[0].contact_extraction_status == "failed"

    @pytest.mark.asyncio
    async def test_existing_lead_data_not_overwritten_by_null(self):
        original_lead = BusinessLead(
            name="Google Verified Business",
            phone="+91 98765 43210",
            address="12 Main St, Nashik",
            email="google@verified.com",
            website="https://verifiedbiz.com",
            source="google",
        )
        mock_scrape_res = {
            "website": "https://verifiedbiz.com",
            "website_available": True,
            "website_accessible": True,
            "scrape_status": "success",
            "scraped_data": {},
        }
        service = ContactExtractionService()
        with patch.object(WebsiteScraper, "scrape_website", return_value=mock_scrape_res):
            with patch("httpx.AsyncClient.get", side_effect=Exception("Timeout")):
                result = await service.extract_lead_contact_info(original_lead)
                # None of original verified fields overwritten
                assert result.name == "Google Verified Business"
                assert result.phone == "+91 98765 43210"
                assert result.address == "12 Main St, Nashik"
                assert result.email == "google@verified.com"

    @pytest.mark.asyncio
    async def test_extraction_does_not_create_duplicate_leads(self):
        leads = [
            BusinessLead(name="Biz A", website="https://biza.com"),
            BusinessLead(name="Biz B", website="https://bizb.com"),
        ]
        service = ContactExtractionService()
        with patch.object(
            WebsiteScraper,
            "scrape_website",
            return_value={"website_accessible": False, "scrape_status": "timeout"},
        ):
            processed = await service.extract_leads_contact_info(leads)
            assert len(processed) == 2
            assert processed[0].name == "Biz A"
            assert processed[1].name == "Biz B"
