from unittest.mock import patch
import pytest

from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead
from app.services.business_info_extraction.description_extractor import (
    extract_business_description,
)
from app.services.business_info_extraction.profile_extractor_service import (
    BusinessProfileExtractionService,
    extract_business_profiles,
)
from app.services.business_info_extraction.services_products_extractor import (
    extract_services_and_products,
)
from app.services.business_info_extraction.target_customer_extractor import (
    extract_target_customers,
)


class TestDescriptionExtraction:
    """1. Test cases for business description extraction (JSON-LD priority)."""

    def test_description_json_ld_priority(self):
        json_ld = [{"@type": "LocalBusiness", "description": "JSON-LD High Quality Description"}]
        html = '<html><head><meta name="description" content="Meta Description"></head></html>'
        desc = extract_business_description(html, json_ld)
        assert desc == "JSON-LD High Quality Description"

    def test_description_meta_fallback(self):
        html = '<html><head><meta name="description" content="Meta Description Only"></head></html>'
        desc = extract_business_description(html, [])
        assert desc == "Meta Description Only"

    def test_description_missing_returns_none(self):
        html = "<html><body></body></html>"
        desc = extract_business_description(html, [])
        assert desc is None


class TestServicesAndProductsExtraction:
    """2-4. Test cases for category, services, and product extraction."""

    def test_service_and_product_extraction_from_json_ld(self):
        json_ld = [
            {"@type": "Service", "name": "Web Development"},
            {"@type": "Product", "name": "SDR Automation Software"},
        ]
        services, products = extract_services_and_products("<html></html>", json_ld)
        assert "Web Development" in services
        assert "SDR Automation Software" in products

    def test_services_from_html_section(self):
        html = """
        <html>
        <body>
            <h2>Our Services</h2>
            <p>SEO Optimization, Digital Marketing, Content Strategy</p>
        </body>
        </html>
        """
        services, products = extract_services_and_products(html, [])
        assert "SEO Optimization" in services or any("SEO" in s for s in services)


class TestTargetCustomerExtraction:
    """5-6. Test cases for explicit target customer extraction and anti-hallucination."""

    def test_explicit_target_customer_extracted(self):
        html = "<html><body><p>We provide services for small businesses and healthcare providers.</p></body></html>"
        targets = extract_target_customers(html)
        assert any("small businesses" in t.lower() for t in targets)

    def test_target_customer_empty_when_not_explicitly_mentioned(self):
        html = "<html><body><p>Welcome to our dental clinic. We are open Monday to Friday.</p></body></html>"
        targets = extract_target_customers(html)
        assert targets == []  # Anti-hallucination check


class TestBusinessProfileCreationAndPipeline:
    """7-16. Test cases for BusinessProfile model creation, linkage, duplicate prevention, and provider compatibility."""

    @pytest.mark.asyncio
    async def test_build_business_profile_from_google_lead(self):
        lead = BusinessLead(
            external_place_id="ChIJ_google_999",
            source="google",
            name="Google Dental Care",
            category="Dentist",
            address="10 Station Rd, Nashik",
            phone="+919876543210",
            email="info@googledental.com",
            website="https://googledental.com",
            description="Premier dental care facility.",
            services=["Teeth Whitening", "Root Canal"],
        )

        service = BusinessProfileExtractionService()

        with patch("httpx.AsyncClient.get", side_effect=Exception("Offline")):
            profile = await service.build_business_profile(lead)
            assert isinstance(profile, BusinessProfile)
            assert profile.lead_id == "ChIJ_google_999"
            assert profile.source == "google"
            assert profile.business_name == "Google Dental Care"
            assert profile.category == "Dentist"
            assert profile.phone == "+919876543210"
            assert profile.email == "info@googledental.com"
            assert "Teeth Whitening" in profile.services

    @pytest.mark.asyncio
    async def test_build_business_profile_from_foursquare_lead(self):
        lead = BusinessLead(
            external_place_id="fsq_place_888",
            source="foursquare",
            name="FSQ Cafe Coffee",
            category="Coffee Shop",
            address="22 College Rd",
            phone="+919800011111",
            website="https://fsqcoffee.com",
        )

        service = BusinessProfileExtractionService()
        with patch("httpx.AsyncClient.get", side_effect=Exception("Offline")):
            profile = await service.build_business_profile(lead)
            assert profile.source == "foursquare"
            assert profile.business_name == "FSQ Cafe Coffee"
            assert profile.category == "Coffee Shop"

    @pytest.mark.asyncio
    async def test_no_website_lead_profile_creation(self):
        lead = BusinessLead(
            name="No Website Store",
            category="Retail",
            website=None,
        )

        service = BusinessProfileExtractionService()
        profile = await service.build_business_profile(lead)
        assert profile.profile_extraction_status == "skipped"
        assert profile.extraction_source == "provider_only"
        assert profile.website is None

    @pytest.mark.asyncio
    async def test_duplicate_profile_prevention_in_batch(self):
        leads = [
            BusinessLead(external_place_id="place_1", name="Shop A"),
            BusinessLead(external_place_id="place_1", name="Shop A Duplicate"),
            BusinessLead(external_place_id="place_2", name="Shop B"),
        ]

        service = BusinessProfileExtractionService()
        with patch("httpx.AsyncClient.get", side_effect=Exception("Offline")):
            _, profiles = await service.extract_business_profiles(leads)
            assert len(profiles) == 2
            place_ids = [p.external_place_id for p in profiles]
            assert place_ids == ["place_1", "place_2"]
