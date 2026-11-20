from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.agents.lead_pipeline.schema import BusinessRecord, LeadResult, WebsitePage
from app.agents.lead_pipeline.pipeline import _extract_offerings
from app.agents.lead_pipeline.scoring import score_lead
from app.agents.lead_pipeline.schema import PlacesConfig
from app.agents.research.agent import ground_research_result, research_agent
from app.api.v1.research import competitor_analysis
from app.integrations.google_places import GooglePlacesClient
from app.services.ai_agents import analyze_competitors
from app.services.research_outputs import ResearchOutputService


class ResearchQualityTests(unittest.TestCase):
    def test_score_contains_dimension_and_factor_breakdown(self):
        score = score_lead({
            "business": {
                "business_name": "Fixture Gym",
                "category": "Gym",
                "website": "https://fixture.test",
                "rating": 4.5,
                "review_count": 80,
                "phone": "+919876543210",
            },
            "profile": {"services": ["Personal training"], "target_customers": []},
            "website_analysis": {
                "status": "active",
                "website_url": "https://fixture.test",
                "website_content": [{
                    "page_url": "https://fixture.test",
                    "page_title": "Fixture Gym",
                    "meta_description": "Fitness services",
                    "main_text": "Fitness " * 100,
                    "technology_signals": ["meta-viewport:width=device-width"],
                }],
                "pages_visited": ["https://fixture.test"],
            },
            "contacts": {"phone_numbers": [{"normalized": "+919876543210"}]},
            "social_links": {},
            "extraction_metadata": {
                "module_status": {
                    "profile": "success",
                    "website": "success",
                    "contacts": "success",
                    "social": "not_available",
                }
            },
        })
        self.assertIn("dimensions", score["score_breakdown"])
        self.assertIn(
            "google_rating",
            score["score_breakdown"]["dimensions"]["business_reputation"]["factors"],
        )
        self.assertGreater(score["score_breakdown"]["assessable_points"], 0)
        result = LeadResult(
            lead_id="fixture",
            discovery={"business_name": "Fixture Gym", "category": "Gym"},
            enrichment={},
            scoring=score,
        )
        serialized = result.model_dump(mode="json")
        self.assertIn(
            "google_rating",
            serialized["scoring"]["score_breakdown"]["dimensions"]["business_reputation"]["factors"],
        )
        legacy = LeadResult(
            lead_id="legacy",
            discovery={"business_name": "Legacy Fixture"},
            enrichment={},
            scoring={
                "score_breakdown": {
                    "api_key": "must-not-serialize",
                }
            },
        ).model_dump(mode="json")
        self.assertNotIn("must-not-serialize", str(legacy))


    def test_summary_does_not_repeat_unsupported_model_claims(self):
        result = ground_research_result(
            {
                "business_name": "Gold's Gym",
                "category": "Fitness center",
                "address": "Nashik",
                "description": "Gym with strength and group training.",
                "services": ["Strength training"],
            },
            {"business_summary": "A leading gym with a strong national presence."},
        )
        self.assertTrue(
            result["business_summary"].startswith(
                "Gold's Gym: Gym with strength and group training."
            )
        )
        self.assertNotIn("leading", result["business_summary"])

    def test_report_uses_listing_evidence_and_filters_scraped_cta_copy(self):
        result = ground_research_result(
            {
                "business_name": "Gold's Gym",
                "category": "Gym",
                "address": "Nashik",
                "description": "Fitness club.",
                "services": [
                    "Strength training",
                    "Why choose us",
                    "Design & Developed By Brand Beavers",
                ],
                "rating": 4.0,
                "review_count": 120,
                "website": "https://goldsgym.example",
                "phone": "+919876543210",
                "contacts": {"contact_person": {"value": "Asha Patel"}},
            },
            {},
        )
        self.assertIn("120 reviews", result["business_summary"])
        self.assertEqual(result["products_services"], ["Strength training"])
        self.assertTrue(any("Strength training" in item for item in result["sales_opportunities"]))
        self.assertIn("Asha Patel", result["decision_maker_identification"])
        self.assertTrue(any("Address is Nashik" == fact for fact in result["provided_facts"]))
        self.assertFalse(any("Brand Beavers" in item for item in result["products_services"]))

    def test_malformed_model_json_falls_back_without_a_second_generation(self):
        lead = {
            "lead_id": "lead-1",
            "business_name": "Gold's Gym",
            "category": "Fitness center",
            "address": "Nashik",
            "description": "Gym with strength and group training.",
            "services": ["Strength training"],
            "products": [],
            "target_customers": [],
        }
        with patch(
            "app.agents.research.agent.generate",
            return_value='{"business_summary": "truncated',
        ) as generate:
            result = research_agent(lead)

        self.assertEqual(generate.call_count, 1)
        self.assertTrue(
            result["business_summary"].startswith(
                "Gold's Gym: Gym with strength and group training."
            )
        )
        self.assertEqual(result["products_services"], ["Strength training"])
        self.assertIsNotNone(result["researched_at"])

    def test_offerings_skip_promotional_headings_and_website_credits(self):
        page = WebsitePage(
            page_url="https://example.test/services",
            page_type="services",
            main_text=(
                "Why choose us\n"
                "Personal Training\n"
                "What Do We Do\n"
                "Design & Developed By Brand Beavers\n"
                "Strength Training"
            ),
        )
        offerings = _extract_offerings([page], "service")
        self.assertEqual([item.value for item in offerings], ["Personal Training", "Strength Training"])


class CompetitorAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_places_search_uses_nearby_location_bias(self):
        client = GooglePlacesClient(
            config=PlacesConfig(api_key="fixture"),
            client=Mock(),
        )
        client._request_page = AsyncMock(return_value={"places": []})
        await client.search(
            "Gym",
            "Nashik",
            8,
            location_bias=(19.9975, 73.7898, 10_000),
        )
        body = client._request_page.await_args.args[1]
        self.assertEqual(
            body["locationBias"]["circle"],
            {
                "center": {"latitude": 19.9975, "longitude": 73.7898},
                "radius": 10_000,
            },
        )

    async def test_search_excludes_subject_and_persists_comparison(self):
        lead = LeadResult(
            lead_id="lead-1",
            discovery={
                "business_name": "Gold's Gym",
                "category": "Gym",
                "address": "Nashik",
                "rating": 4.0,
                "latitude": 19.9975,
                "longitude": 73.7898,
            },
            enrichment={},
            scoring={},
        )
        records = [
            BusinessRecord(
                lead_id="same-place",
                business_name="Golds Gym",
                category="Gym",
                address="Nashik",
                rating=4.0,
            ),
            BusinessRecord(
                lead_id="competitor",
                business_name="Example Fitness",
                category="Gym",
                address="Nashik",
                latitude=19.998,
                longitude=73.790,
                rating=4.5,
                review_count=120,
                discovery_source="google_places",
                source_url="https://maps.example.test/place",
            ),
            BusinessRecord(
                lead_id="too-far",
                business_name="Distant Gym",
                category="Gym",
                address="Far away",
                latitude=20.2,
                longitude=73.8,
            ),
            BusinessRecord(
                lead_id="wrong-category",
                business_name="Nearby Dental Clinic",
                category="Dentist",
                address="Nearby",
                latitude=19.998,
                longitude=73.790,
            ),
        ]

        class Settings:
            lead_json_path = "unused"
            research_root = "unused"

        output_store = Mock()

        with (
            patch("app.services.ai_agents.DiscoverySettings") as settings_cls,
            patch("app.services.ai_agents._search_competitor_places", new=AsyncMock(return_value=records)),
            patch("app.services.ai_agents.get_settings", return_value=Settings()),
            patch("app.services.ai_agents.ResearchOutputService", return_value=output_store),
        ):
            settings_cls.return_value.leadsutra_enable_google_places = True
            settings_cls.return_value.leadsutra_enable_maps_browser = True
            settings_cls.return_value.leadsutra_competitor_radius_meters = 10_000
            result = await analyze_competitors(lead)

        self.assertEqual([item["name"] for item in result["competitors"]], ["Example Fitness"])
        self.assertIn("average listed rating is 4.5/5", result["comparison_summary"])
        self.assertEqual(result["competitors"][0]["distance_meters"], 59)
        self.assertEqual(result["status"], "complete")
        output_store.save_competitors.assert_called_once_with("lead-1", result)

    async def test_competitor_endpoint_returns_saved_analysis(self):
        lead = LeadResult(
            lead_id="lead-1",
            discovery={"business_name": "Gold's Gym"},
            enrichment={},
            scoring={},
        )
        cached = {
            "business_name": "Gold's Gym",
            "category": "Gym",
            "location": "Nashik",
            "status": "complete",
            "source": "google_places",
            "radius_meters": 10000,
            "competitors": [],
            "comparison_summary": "No competitors found.",
            "message": None,
            "researched_at": "2026-10-15T08:00:00+00:00",
        }
        lead_store = Mock()
        lead_store.get_by_id.return_value = lead
        with (
            patch("app.api.v1.research.get_settings", return_value=Mock(lead_json_path="unused")),
            patch("app.api.v1.research.DiscoverySettings", return_value=Mock(leadsutra_competitor_radius_meters=10000)),
            patch("app.api.v1.research.LeadResultStore", return_value=lead_store),
            patch("app.api.v1.research.get_competitor_analysis", return_value=cached),
        ):
            result = await competitor_analysis("lead-1", refresh=False)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.business_name, "Gold's Gym")

    def test_competitor_analysis_is_saved_and_loaded(self):
        collection = Mock()
        collection.find_one.return_value = {
            "competitor_analysis": {"status": "complete", "competitors": []}
        }
        with patch("app.services.research_outputs.get_mongo_collection", return_value=collection):
            store = ResearchOutputService("unused")
            store.save_competitors("lead-1", {"status": "complete", "competitors": []})
            loaded = store.load_competitors("lead-1")

        self.assertEqual(loaded, {"status": "complete", "competitors": []})
        collection.update_one.assert_called_once()


if __name__ == "__main__":
    unittest.main()
