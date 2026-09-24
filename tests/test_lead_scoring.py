from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead
from app.models.lead_score import LeadScoreResult
from app.services.lead_scoring.config import LeadScoringConfig
from app.services.lead_scoring.scorers import (
    score_business_category,
    score_business_size,
    score_contact_availability,
    score_online_presence,
    score_website_availability,
)
from app.services.lead_scoring.scoring_service import (
    LeadScoringService,
    score_lead,
    score_leads,
)


class TestScoringFactors:
    """1-18. Unit tests for individual scoring parameter calculation functions."""

    def test_category_scoring(self):
        assert score_business_category("Dental Clinic", "Dentist") == 18
        assert score_business_category("Restaurant", "Restaurant") == 25
        assert score_business_category(None, "Restaurant") == 0

    def test_website_availability_scoring(self):
        assert score_website_availability("accessible", "https://example.com") == 20
        assert score_website_availability("blocked", "https://example.com") == 9
        assert score_website_availability("no_website", None) == 0

    def test_online_presence_scoring(self):
        socials_3 = {"instagram": "url1", "facebook": "url2", "linkedin": "url3"}
        socials_1 = {"instagram": "url1"}

        assert score_online_presence(socials_3, "accessible") == 20
        assert score_online_presence(socials_1, "accessible") == 13
        assert score_online_presence({}, "accessible") == 7
        assert score_online_presence({}, "no_website") == 0

    def test_contact_availability_scoring(self):
        # Email + Phone + Person = 25
        assert score_contact_availability("info@biz.com", "+919876543210", "John Doe") == 25
        # Email + Phone = 18
        assert score_contact_availability("info@biz.com", "+919876543210", None) == 18
        # Only Phone = 12
        assert score_contact_availability(None, "+919876543210", None) == 12
        # None = 0
        assert score_contact_availability(None, None, None) == 0

    def test_business_size_scoring(self):
        profile_large = BusinessProfile(
            business_name="Large Corp",
            services=["S1", "S2", "S3", "S4", "S5"],
            products=["P1", "P2", "P3", "P4", "P5"],
        )
        profile_small = BusinessProfile(
            business_name="Small Shop",
            services=["S1"],
        )

        assert score_business_size(profile_large) == 10
        assert score_business_size(profile_small) == 6
        assert score_business_size(None) == 2


class TestLeadScoringService:
    """19-26. Integration tests for lead scoring service, priorities, breakdowns, and provider independence."""

    def test_high_scoring_lead(self):
        lead = BusinessLead(
            external_place_id="place_high",
            source="google",
            name="Apex Dental Care",
            category="Dentist",
            rating=4.8,
            phone="+919876543210",
            email="info@apexdental.com",
            website="https://apexdental.com",
            website_status="accessible",
            contact_person="Dr. Jatin Shewale",
            social_links={"instagram": "url1", "facebook": "url2", "linkedin": "url3"},
        )
        profile = BusinessProfile(
            business_name="Apex Dental Care",
            services=["Teeth Whitening", "Root Canal", "Implants", "Braces", "Checkup"],
        )

        updated_lead, result = score_lead(lead, profile=profile, target_category="Dentist")

        assert result.lead_score >= 75
        assert result.priority == "high"
        assert result.qualification_status == "qualified"
        assert updated_lead.lead_score == result.lead_score
        assert updated_lead.priority == "high"

    def test_medium_scoring_lead(self):
        lead = BusinessLead(
            name="Medium Cafe",
            category="Cafe",
            rating=4.0,
            phone="+919876543210",
            website="https://mediumcafe.com",
            website_status="accessible",
        )
        _, result = score_lead(lead, target_category="Cafe")

        assert 50 <= result.lead_score < 75
        assert result.priority == "medium"
        assert result.qualification_status == "partially_qualified"

    def test_low_scoring_lead(self):
        lead = BusinessLead(
            name="Unknown Basic Store",
            category=None,
            website=None,
            phone=None,
        )
        _, result = score_lead(lead)

        assert result.lead_score < 50
        assert result.priority == "low"
        assert result.qualification_status == "unqualified"

    def test_provider_independence_google_vs_foursquare(self):
        google_lead = BusinessLead(
            external_place_id="g_123",
            source="google",
            name="Royal Hotel",
            category="Hotel",
            rating=4.5,
            phone="+919876500000",
            website="https://royalhotel.com",
            website_status="accessible",
        )
        foursquare_lead = BusinessLead(
            external_place_id="fsq_123",
            source="foursquare",
            name="Royal Hotel",
            category="Hotel",
            rating=4.5,  # Normalized 9.0/2 = 4.5
            phone="+919876500000",
            website="https://royalhotel.com",
            website_status="accessible",
        )

        _, g_result = score_lead(google_lead, target_category="Hotel")
        _, f_result = score_lead(foursquare_lead, target_category="Hotel")

        # Equivalent normalized attributes MUST produce identical scores
        assert g_result.lead_score == f_result.lead_score
        assert g_result.score_breakdown == f_result.score_breakdown

    def test_score_breakdown_totals_correctly(self):
        lead = BusinessLead(
            name="Test Biz",
            category="IT Services",
            rating=4.2,
            website="https://testbiz.com",
            website_status="accessible",
            phone="+919999900000",
            email="contact@testbiz.com",
        )
        _, result = score_lead(lead, target_category="IT Services")

        sum_breakdown = sum(result.score_breakdown.values())
        assert sum_breakdown == result.lead_score

    def test_missing_data_safety_no_crashes(self):
        empty_lead = BusinessLead(name="Bare Minimum")
        updated_lead, result = score_lead(empty_lead)

        assert result.lead_score >= 0
        assert updated_lead.lead_score == result.lead_score
        assert result.priority == "low"

    def test_batch_scoring(self):
        leads = [
            BusinessLead(name="Biz 1", category="Tech", rating=4.9, website="https://b1.com", website_status="accessible"),
            BusinessLead(name="Biz 2", category=None, website=None),
        ]
        scored_leads, results = score_leads(leads, target_category="Tech")

        assert len(scored_leads) == 2
        assert len(results) == 2
        assert results[0].lead_score > results[1].lead_score
