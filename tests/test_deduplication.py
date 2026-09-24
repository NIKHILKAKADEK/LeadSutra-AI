import pytest
from app.models.lead import BusinessLead
from app.services.lead_discovery.deduplication import (
    are_leads_duplicate,
    deduplicate_leads,
    merge_leads,
)
from app.services.lead_discovery.normalizers import (
    haversine_distance_meters,
    normalize_address,
    normalize_business_name,
    normalize_phone,
    normalize_website_domain,
)


class TestNormalizers:
    """Unit tests for individual normalization functions."""

    def test_normalize_phone(self):
        assert normalize_phone("+91 (987) 654-3210") == "+919876543210"
        assert normalize_phone("9876543210") == "+919876543210"
        assert normalize_phone("+1-800-555-0199") == "+18005550199"
        assert normalize_phone(None) is None
        assert normalize_phone("") is None
        assert normalize_phone("   ") is None

    def test_normalize_website_domain(self):
        assert normalize_website_domain("https://www.example.com/path/to/page") == "example.com"
        assert normalize_website_domain("http://example.org:8080/") == "example.org"
        assert normalize_website_domain("WWW.LEADSUTRA.AI") == "leadsutra.ai"
        assert normalize_website_domain(None) is None
        assert normalize_website_domain("") is None

    def test_normalize_business_name(self):
        assert normalize_business_name("Acme Solutions Pvt. Ltd.") == "acme solutions"
        assert normalize_business_name("Global Tech, Inc.") == "global tech"
        assert normalize_business_name("Taj Mahal Restaurant LLC") == "taj mahal restaurant"
        assert normalize_business_name(None) is None
        assert normalize_business_name("") is None

    def test_normalize_address(self):
        assert normalize_address("123 Main St., Apt 4B") == "123 main street apartment 4b"
        assert normalize_address("456 College Rd, Ste 100") == "456 college road suite 100"
        assert normalize_address(None) is None
        assert normalize_address("") is None

    def test_haversine_distance(self):
        # Same point = 0 meters
        dist_zero = haversine_distance_meters(19.9975, 73.7898, 19.9975, 73.7898)
        assert dist_zero is not None and abs(dist_zero) < 0.01

        # Known nearby points (~50 meters apart)
        dist_near = haversine_distance_meters(19.9975, 73.7898, 19.9978, 73.7898)
        assert dist_near is not None and 30 < dist_near < 70

        # Known far points (>1km apart)
        dist_far = haversine_distance_meters(19.9975, 73.7898, 20.0100, 73.8000)
        assert dist_far is not None and dist_far > 1000

        # Missing coordinate returns None
        assert haversine_distance_meters(None, 73.7898, 19.9975, 73.7898) is None


class TestDeduplication:
    """Unit tests for duplicate detection, merging, and batch deduplication."""

    def test_duplicate_by_phone(self):
        lead1 = BusinessLead(name="Hotel City Center", phone="+91 98765 43210")
        lead2 = BusinessLead(name="City Center Hotel", phone="09876543210")
        is_dup, reason = are_leads_duplicate(lead1, lead2)
        assert is_dup is True
        assert reason == "phone_match"

    def test_duplicate_by_domain(self):
        lead1 = BusinessLead(name="Alpha Tech", website="https://www.alphatech.io/about")
        lead2 = BusinessLead(name="Alpha Tech Solutions", website="http://alphatech.io")
        is_dup, reason = are_leads_duplicate(lead1, lead2)
        assert is_dup is True
        assert reason == "domain_match"

    def test_duplicate_by_name_and_geo(self):
        lead1 = BusinessLead(
            name="Spice Grill Restaurant Pvt Ltd",
            latitude=19.99750,
            longitude=73.78980,
        )
        lead2 = BusinessLead(
            name="Spice Grill Restaurant",
            latitude=19.99752,  # ~2 meters away
            longitude=73.78981,
        )
        is_dup, reason = are_leads_duplicate(lead1, lead2)
        assert is_dup is True
        assert reason == "name_geo_match"

    def test_not_duplicate_by_name_and_geo_distant(self):
        lead1 = BusinessLead(
            name="Spice Grill Restaurant",
            latitude=19.9975,
            longitude=73.7898,
        )
        lead2 = BusinessLead(
            name="Spice Grill Restaurant",
            latitude=20.0500,  # ~5.8 km away
            longitude=73.8500,
        )
        is_dup, reason = are_leads_duplicate(lead1, lead2)
        assert is_dup is False
        assert reason == "no_match"

    def test_duplicate_by_name_and_address(self):
        lead1 = BusinessLead(
            name="Apex Clinic Ltd",
            address="12 MG Rd, Nashik",
        )
        lead2 = BusinessLead(
            name="Apex Clinic",
            address="12 MG Road, Nashik",
        )
        is_dup, reason = are_leads_duplicate(lead1, lead2)
        assert is_dup is True
        assert reason == "name_address_match"

    def test_non_duplicate_leads(self):
        lead1 = BusinessLead(name="Royal Bakery", address="10 College Rd")
        lead2 = BusinessLead(name="Star Supermarket", address="20 Main St")
        is_dup, reason = are_leads_duplicate(lead1, lead2)
        assert is_dup is False
        assert reason == "no_match"

    def test_merge_leads_prefer_google(self):
        google_lead = BusinessLead(
            name="Grand Hotel",
            address="10 Station Rd",
            phone="+919876500000",
            website=None,  # Missing in Google
            rating=4.5,
            external_place_id="ChIJ_google_123",
            source="google",
            raw_data={"google_id": "123"},
        )
        foursquare_lead = BusinessLead(
            name="Grand Hotel & Suites",
            address="10 Station Road, Landmark",
            phone="+919876500000",
            website="https://grandhotel.com",  # Present in Foursquare
            rating=4.2,  # 8.4/2 = 4.2
            external_place_id="fsq_456",
            source="foursquare",
            raw_data={"fsq_id": "456"},
        )

        merged = merge_leads(google_lead, foursquare_lead)

        assert merged.source == "google"
        assert merged.name == "Grand Hotel"
        assert merged.phone == "+919876500000"
        assert merged.website == "https://grandhotel.com"  # Filled from secondary
        assert merged.rating == 4.5  # Kept from primary
        assert merged.external_place_id == "ChIJ_google_123"
        assert "merged_sources" in merged.raw_data
        assert len(merged.raw_data["merged_sources"]) == 2

    def test_deduplicate_leads_batch(self):
        leads = [
            BusinessLead(name="Cafe Coffee Day", phone="+919800011111", source="google"),
            BusinessLead(name="CCD", phone="09800011111", website="https://cafecoffeeday.com", source="foursquare"),
            BusinessLead(name="Unique Bakery", phone="+919899900000", source="google"),
        ]

        deduped = deduplicate_leads(leads)

        assert len(deduped) == 2
        # CCD merged into Cafe Coffee Day
        ccd_lead = next(l for l in deduped if "Coffee" in l.name)
        assert ccd_lead.website == "https://cafecoffeeday.com"
        assert ccd_lead.source == "google"

    def test_deduplicate_leads_empty_and_single(self):
        assert deduplicate_leads([]) == []
        single_lead = BusinessLead(name="Single Business")
        assert len(deduplicate_leads([single_lead])) == 1
