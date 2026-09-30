from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.models.lead import BusinessLead
from app.services.website_scraping.enrichment_service import (
    WebsiteEnrichmentService,
    enrich_lead,
)
from app.services.website_scraping.extractors import (
    extract_business_info_from_html,
    extract_business_info_from_json_ld,
)
from app.services.website_scraping.html_parser import (
    extract_json_ld,
    extract_social_links,
)
from app.services.website_scraping.scraper import WebsiteScraper
from app.services.website_scraping.url_validator import validate_and_normalize_url
from app.services.website_scraping.website_detector import WebsiteDetector


class TestURLValidator:
    """1-3. Test cases for URL validation and normalization."""

    def test_valid_website_url(self):
        is_valid, norm_url, status = validate_and_normalize_url("https://www.example.com/about/")
        assert is_valid is True
        assert norm_url == "https://www.example.com/about"
        assert status == "valid_url"

    def test_url_without_protocol(self):
        is_valid, norm_url, status = validate_and_normalize_url("leadsutra.ai")
        assert is_valid is True
        assert norm_url == "https://leadsutra.ai"
        assert status == "valid_url"

    def test_invalid_url(self):
        is_valid, norm_url, status = validate_and_normalize_url("not a domain!@#")
        assert is_valid is False
        assert norm_url is None
        assert status == "invalid_url"

    def test_no_website(self):
        is_valid, norm_url, status = validate_and_normalize_url(None)
        assert is_valid is False
        assert norm_url is None
        assert status == "no_website"


class TestWebsiteDetector:
    """4-8. Test cases for website availability and accessibility checking."""

    @pytest.mark.asyncio
    async def test_accessible_website(self):
        detector = WebsiteDetector()

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.com"

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            res = await detector.detect_and_check("example.com")
            assert res["website_available"] is True
            assert res["website_accessible"] is True
            assert res["website_status"] == "accessible"

    @pytest.mark.asyncio
    async def test_website_timeout(self):
        detector = WebsiteDetector()

        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
            res = await detector.detect_and_check("https://slowwebsite.com")
            assert res["website_available"] is True
            assert res["website_accessible"] is False
            assert res["website_status"] == "timeout"

    @pytest.mark.asyncio
    async def test_http_error_website(self):
        detector = WebsiteDetector()

        mock_response = AsyncMock()
        mock_response.status_code = 500

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            res = await detector.detect_and_check("https://broken.com")
            assert res["website_available"] is True
            assert res["website_accessible"] is False
            assert res["website_status"] == "inaccessible"

    @pytest.mark.asyncio
    async def test_redirect_website(self):
        detector = WebsiteDetector()

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.com/en/"

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            res = await detector.detect_and_check("example.com")
            assert res["website_accessible"] is True
            assert res["redirect_url"] == "https://example.com/en/"


class TestHTMLExtraction:
    """9-13. Test cases for JSON-LD, description, and social media extraction."""

    def test_json_ld_extraction(self):
        html_str = """
        <html>
        <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": "Apex Dental Clinic",
            "description": "Leading dental care in Nashik",
            "telephone": "+91 98765 43210",
            "address": {
                "streetAddress": "12 College Road",
                "addressLocality": "Nashik"
            }
        }
        </script>
        </head>
        </html>
        """
        json_lds = extract_json_ld(html_str)
        assert len(json_lds) == 1
        info = extract_business_info_from_json_ld(json_lds)
        assert info["name"] == "Apex Dental Clinic"
        assert info["description"] == "Leading dental care in Nashik"
        assert info["phone"] == "+91 98765 43210"

    def test_business_description_meta_and_text_extraction(self):
        html_str = """
        <html>
        <head>
            <title>Star Hospital - About Us</title>
            <meta name="description" content="Star Hospital provides 24/7 emergency healthcare services.">
        </head>
        <body>
            <h1>Star Hospital</h1>
            <p>Welcome to Star Hospital, the premier medical facility.</p>
        </body>
        </html>
        """
        info = extract_business_info_from_html(html_str, "https://starhospital.com")
        assert info["name"] == "Star Hospital"
        assert info["meta_description"] == "Star Hospital provides 24/7 emergency healthcare services."
        assert info["description"] == "Star Hospital provides 24/7 emergency healthcare services."

    def test_social_media_links_extraction(self):
        html_str = """
        <html>
        <body>
            <a href="https://facebook.com/mybusiness">Facebook</a>
            <a href="https://instagram.com/mybusiness_official">Instagram</a>
            <a href="https://linkedin.com/company/mybusiness">LinkedIn</a>
            <a href="https://x.com/mybusiness">Twitter</a>
            <a href="https://youtube.com/@mybusiness">YouTube</a>
        </body>
        </html>
        """
        socials = extract_social_links(html_str)
        assert socials["facebook"] == "https://facebook.com/mybusiness"
        assert socials["instagram"] == "https://instagram.com/mybusiness_official"
        assert socials["linkedin"] == "https://linkedin.com/company/mybusiness"
        assert socials["twitter"] == "https://x.com/mybusiness"
        assert socials["youtube"] == "https://youtube.com/@mybusiness"

    def test_missing_html_fields_gracefully_handled(self):
        html_str = "<html><body></body></html>"
        info = extract_business_info_from_html(html_str, "https://empty.com")
        assert info["description"] is None
        assert info["phone"] is None
        assert info["social_links"] == {}


class TestLeadEnrichment:
    """14-16. Test cases for non-destructive lead enrichment and pipeline safety."""

    @pytest.mark.asyncio
    async def test_existing_lead_data_is_preserved(self):
        original_lead = BusinessLead(
            name="Google Original Name",
            phone="+91 99999 88888",
            address="Original Google Address",
            website="https://mybusiness.com",
            source="google",
        )

        mock_scrape_res = {
            "website": "https://mybusiness.com",
            "website_available": True,
            "website_accessible": True,
            "scrape_status": "success",
            "scraped_data": {
                "name": "Different Scraped Name",
                "phone": "+1 800 000 0000",
                "address": "Scraped Address",
                "description": "Scraped high quality business description.",
                "social_links": {"instagram": "https://instagram.com/mybusiness"},
                "services": ["Service A"],
            },
            "scrape_error": None,
        }

        service = WebsiteEnrichmentService()
        with patch.object(WebsiteScraper, "scrape_website", return_value=mock_scrape_res):
            enriched = await service.enrich_lead(original_lead)

            # Original provider details MUST BE PRESERVED
            assert enriched.name == "Google Original Name"
            assert enriched.phone == "+91 99999 88888"
            assert enriched.address == "Original Google Address"
            assert enriched.source == "google"

            # Missing fields MUST BE FILLED
            assert enriched.description == "Scraped high quality business description."
            assert enriched.social_links["instagram"] == "https://instagram.com/mybusiness"
            assert enriched.services == ["Service A"]
            assert enriched.website_status == "success"

    @pytest.mark.asyncio
    async def test_scraping_failure_does_not_crash_pipeline(self):
        lead = BusinessLead(
            name="Test Business",
            website="https://broken-link.com",
        )

        service = WebsiteEnrichmentService()
        with patch.object(
            WebsiteScraper,
            "scrape_website",
            side_effect=Exception("Catastrophic connection failure"),
        ):
            # Should not raise exception
            enriched = await service.enrich_leads([lead])
            assert len(enriched) == 1
            assert enriched[0].name == "Test Business"
