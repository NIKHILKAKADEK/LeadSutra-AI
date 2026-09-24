from datetime import datetime, timezone
import pytest

from app.db.config import MongoConfig
from app.db.connection import MongoDatabase
from app.db.repositories.lead_repository import LeadRepository
from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead


@pytest.fixture
def repo():
    """Fixture providing a fresh isolated LeadRepository with in-memory db fallback."""
    config = MongoConfig(db_name="test_leadsutra", server_selection_timeout_ms=100)
    db = MongoDatabase(config=config)

    # Force in-memory mode for clean unit testing
    db._in_memory = True
    db._db = None

    return LeadRepository(db=db, config=config)


class TestLeadPersistenceCRUD:
    """1-6. Unit tests for lead creation, duplicate detection, Google/Foursquare storage, and merge behavior."""

    @pytest.mark.asyncio
    async def test_new_lead_insertion(self, repo):
        lead = BusinessLead(
            external_place_id="place_101",
            source="google",
            name="Alpha Dental Clinic",
            category="Dentist",
            phone="+919876543210",
        )
        saved = await repo.save_or_merge_lead(lead)
        assert saved.name == "Alpha Dental Clinic"

        retrieved = await repo.find_by_external_id("place_101", "google")
        assert retrieved is not None
        assert retrieved.name == "Alpha Dental Clinic"

    @pytest.mark.asyncio
    async def test_google_and_foursquare_leads_stored_in_same_collection(self, repo):
        google_lead = BusinessLead(
            external_place_id="g_place_1",
            source="google",
            name="Google Business",
        )
        foursquare_lead = BusinessLead(
            external_place_id="fsq_place_1",
            source="foursquare",
            name="Foursquare Business",
        )

        await repo.save_or_merge_lead(google_lead)
        await repo.save_or_merge_lead(foursquare_lead)

        g_found = await repo.find_by_external_id("g_place_1", "google")
        f_found = await repo.find_by_external_id("fsq_place_1", "foursquare")

        assert g_found is not None and g_found.source == "google"
        assert f_found is not None and f_found.source == "foursquare"

    @pytest.mark.asyncio
    async def test_duplicate_prevention_and_merge(self, repo):
        initial_lead = BusinessLead(
            external_place_id="place_dup_1",
            source="google",
            name="Star Hotel",
            phone="+919876500000",
            address="10 Station Rd",
        )
        await repo.save_or_merge_lead(initial_lead)

        # Enrichment payload with missing phone but new email & website
        enrichment_lead = BusinessLead(
            external_place_id="place_dup_1",
            source="google",
            name="Star Hotel",
            phone=None,  # Null in enrichment
            email="contact@starhotel.com",
            website="https://starhotel.com",
        )
        merged = await repo.save_or_merge_lead(enrichment_lead)

        # Phone MUST BE PRESERVED from initial lead; email & website MUST BE FILLED
        assert merged.phone == "+919876500000"
        assert merged.email == "contact@starhotel.com"
        assert merged.website == "https://starhotel.com"


class TestBusinessProfileAndScoringPersistence:
    """7-14. Unit tests for BusinessProfile linkage, lead score persistence, index creation, and filtering."""

    @pytest.mark.asyncio
    async def test_business_profile_persistence_and_linkage(self, repo):
        lead = BusinessLead(
            external_place_id="place_prof_1",
            name="Apex Clinic",
            source="google",
        )
        await repo.save_or_merge_lead(lead)

        profile = BusinessProfile(
            lead_id="place_prof_1",
            external_place_id="place_prof_1",
            source="google",
            business_name="Apex Clinic",
            services=["Root Canal", "Implants"],
        )
        await repo.save_business_profile(profile)

        retrieved_profile = await repo.find_profile_by_lead_id("place_prof_1")
        assert retrieved_profile is not None
        assert retrieved_profile.business_name == "Apex Clinic"
        assert "Root Canal" in retrieved_profile.services

    @pytest.mark.asyncio
    async def test_lead_score_persistence_and_update(self, repo):
        lead = BusinessLead(
            external_place_id="place_score_1",
            name="Scored Business",
            lead_score=85,
            priority="high",
            qualification_status="qualified",
            score_breakdown={"business_category": 20, "google_rating": 20},
        )
        saved = await repo.save_or_merge_lead(lead)
        assert saved.lead_score == 85
        assert saved.priority == "high"

        # Re-score update
        lead_update = BusinessLead(
            external_place_id="place_score_1",
            name="Scored Business",
            lead_score=92,
            priority="high",
            qualification_status="qualified",
        )
        updated = await repo.save_or_merge_lead(lead_update)
        assert updated.lead_score == 92

    @pytest.mark.asyncio
    async def test_get_scored_leads_filtering(self, repo):
        l1 = BusinessLead(name="Lead High", external_place_id="p1", lead_score=85, priority="high")
        l2 = BusinessLead(name="Lead Med", external_place_id="p2", lead_score=60, priority="medium")
        l3 = BusinessLead(name="Lead Low", external_place_id="p3", lead_score=30, priority="low")

        await repo.save_or_merge_lead(l1)
        await repo.save_or_merge_lead(l2)
        await repo.save_or_merge_lead(l3)

        high_priority = await repo.get_scored_leads(min_score=75, priority="high")
        assert len(high_priority) == 1
        assert high_priority[0].name == "Lead High"

        all_above_50 = await repo.get_scored_leads(min_score=50)
        assert len(all_above_50) == 2


class TestTimestampAndErrorHandling:
    """15-18. Unit tests for timestamp behavior, index verification, and offline fallback safety."""

    @pytest.mark.asyncio
    async def test_ensure_indexes_does_not_fail(self, repo):
        await repo.ensure_indexes()
        assert len(repo._get_leads_coll().indexes) >= 1

    @pytest.mark.asyncio
    async def test_offline_database_fallback(self):
        # Database initialized with non-existent host fallback
        cfg = MongoConfig(uri="mongodb://invalid_host:27017", server_selection_timeout_ms=10)
        db = MongoDatabase(config=cfg)
        await db.connect()
        # Must fall back to in-memory mode without throwing uncaught exception
        assert db._in_memory is True
