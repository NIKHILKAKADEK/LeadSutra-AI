"""Schema and disk-persistence regressions without live provider requests."""

import copy
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from app.agents.lead_pipeline.pipeline import LeadPipeline
from app.agents.lead_pipeline.scoring import score_lead
from app.app import app
from app.agents.lead_pipeline import schemas as discovery
from app.schemas.call_history import CallHistoryItem
from app.agents.lead_pipeline.schemas import LeadDiscoveryRequest, LeadDiscoveryResponse, LeadResult
from app.agents.lead_pipeline.pipeline import canonical_lead_output
from app.services.lead_results import LeadResultStore
from app.services.leads import LeadJsonService
from tests.test_lead_discovery import set_enrichment, business, crawled_website, enriched, pipeline


class SchemaTests(unittest.TestCase):
    def test_compatibility_names_are_the_same_models(self):
        for old, new in [
            ("DiscoverRequest", "LeadDiscoveryRequest"),
            ("DiscoverResponse", "LeadDiscoveryResponse"),
            ("DiscoverySection", "DiscoveryData"),
            ("EnrichmentSection", "EnrichmentData"),
            ("DiscoveryScoringSection", "ScoringData"),
            ("CanonicalLead", "LeadResult"),
        ]:
            with self.subTest(name=new):
                self.assertIs(getattr(discovery, old), getattr(discovery, new))

    def test_request_preserves_the_priority_only_contract(self):
        request = {"query": "agency", "location": "Nashik", "limit": 10, "priority": "high"}
        self.assertEqual(LeadDiscoveryRequest.model_validate(request).model_dump(), request)
        for changes in [{"priority": "medium"}, {"qualification": "qualified"}, {"limit": 0}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                LeadDiscoveryRequest.model_validate(request | changes)

    def test_final_response_round_trip_preserves_all_sections(self):
        lead = canonical_lead_output(enriched(business(0)))
        response = LeadDiscoveryResponse(
            success=True, query="agency", location="Nashik", count=1,
            source="google_places", fallback_used=False, leads=[lead],
        )
        recovered = LeadDiscoveryResponse.model_validate_json(response.model_dump_json())
        self.assertEqual(recovered.model_dump(mode="json"), response.model_dump(mode="json"))
        self.assertEqual(set(recovered.leads[0].model_dump()),
                         {"lead_id", "discovery", "enrichment", "scoring"})

    def test_invalid_or_missing_sections_fail_validation(self):
        valid = canonical_lead_output(enriched(business(0))).model_dump(mode="json")
        for section in ["lead_id", "discovery", "enrichment", "scoring"]:
            data = {key: value for key, value in valid.items() if key != section}
            with self.subTest(section=section), self.assertRaises(ValidationError):
                LeadResult.model_validate(data)
        for section, field, value in [
            ("discovery", "business_name", " "),
            ("enrichment", "services", "not a list"),
            ("enrichment", "social_links", {"twitter": "not a URL"}),
            ("scoring", "lead_score", "not a number"),
        ]:
            data = copy.deepcopy(valid)
            data[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValidationError):
                LeadResult.model_validate(data)
        with self.assertRaises(ValidationError):
            LeadResult.model_validate(valid | {"api_key": "fixture-secret"})

    def test_scoring_serialization_keeps_existing_values_only(self):
        raw = enriched(business(0))
        raw["lead_scoring"] = {
            "lead_score": 82.5, "priority": "High", "qualification_status": "Needs Review",
            "score_breakdown": {"api_key": "fixture-secret"},
        }
        output = canonical_lead_output(raw).model_dump(mode="json")
        self.assertEqual(output["scoring"], {
            "lead_score": 82.5, "priority": "High", "qualification_status": "Needs Review",
        })
        self.assertNotIn("fixture-secret", json.dumps(output))

    def test_openapi_uses_standard_names_without_duplicate_models(self):
        schemas = app.openapi()["components"]["schemas"]
        for name in ["LeadDiscoveryRequest", "LeadDiscoveryResponse", "DiscoveryData",
                     "EnrichmentData", "ScoringData", "LeadResult"]:
            self.assertIn(name, schemas)
        for old in ["DiscoverRequest", "DiscoverResponse", "CanonicalLead"]:
            self.assertNotIn(old, schemas)
        self.assertEqual(set(schemas["ScoringData"]["properties"]),
                         {"lead_score", "priority", "qualification_status"})

    def test_retired_fields_cannot_leak_from_nested_models(self):
        record = business(0, sub_category="Dentist", source_ref="places/place_0",
                          website="http://fixture.example")
        lead = canonical_lead_output(enriched(record))
        # Excluded inherited fields remain excluded even after assignment.
        lead.discovery.sub_category = "Clinic"
        lead.discovery.source_ref = "internal-only"
        for mode in ["python", "json"]:
            with self.subTest(mode=mode):
                output = lead.model_dump(mode=mode, serialize_as_any=True)
                self.assertFalse({"sub_category", "source_ref"} & output["discovery"].keys())
                self.assertFalse({"final_url", "operating_hours"} & output["enrichment"].keys())
                self.assertEqual(output["discovery"]["source_url"], record.source_url)
                self.assertEqual(output["discovery"]["website"], record.website)
        self.assertNotIn("internal-only", lead.model_dump_json())
        schemas = app.openapi()["components"]["schemas"]
        self.assertFalse({"sub_category", "source_ref"} & schemas["DiscoveryData"]["properties"].keys())
        self.assertFalse({"final_url", "operating_hours"} & schemas["EnrichmentData"]["properties"].keys())
        self.assertTrue({"source_url", "website"} <= schemas["DiscoveryData"]["properties"].keys())
        self.assertTrue({"website_url", "website_status"} <= schemas["EnrichmentData"]["properties"].keys())

    def test_existing_call_result_contract_remains_consumable(self):
        result = CallHistoryItem.model_validate({
            "call_id": str(uuid4()), "lead_id": "lead_000", "phone_number": "+919876543210",
            "dispatch_status": "dispatched", "provider_request_id": "fixture-request",
            "dispatch_requested": True, "provider_accepted": True,
            "created_at": "2026-10-08T10:00:00Z", "updated_at": "2026-10-08T10:00:00Z",
        })
        self.assertEqual(result.call_outcome, "unknown")
        self.assertEqual(CallHistoryItem.model_validate_json(result.model_dump_json()), result)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "leads"
        self.store = LeadResultStore(self.root)
        self.lead = canonical_lead_output(enriched(business(0, business_name="Fixture Café")))

    def test_json_round_trip_preserves_values_order_and_unicode(self):
        leads = [self.lead, canonical_lead_output(enriched(business(1)))]
        original = [lead.model_dump(mode="json") for lead in leads]
        path = self.store.save(leads)
        self.assertEqual(path.name, "leads.json")
        self.assertEqual(path.parent.parent, self.root)
        UUID(path.parent.name)
        text = path.read_text(encoding="utf-8")
        self.assertIn("Café", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text), original)
        recovered = LeadResultStore(self.root).load(path.parent.name)
        self.assertEqual([lead.model_dump(mode="json") for lead in recovered], original)
        self.assertEqual([lead.model_dump(mode="json") for lead in leads], original)

    def test_legacy_artifacts_are_readable_without_reintroducing_retired_fields(self):
        path = self.store.save([self.lead])
        expected = json.loads(path.read_text(encoding="utf-8"))
        legacy = copy.deepcopy(expected)
        legacy[0]["discovery"].update(sub_category="Clinic", source_ref="places/legacy")
        legacy[0]["enrichment"].update(
            final_url="https://fixture.example/",
            operating_hours={"Monday": {"opens": "09:00", "closes": "17:00", "closed": False}},
        )
        path.write_text(json.dumps(legacy), encoding="utf-8")
        original_bytes = path.read_bytes()
        loaded = self.store.load(path.parent.name)
        self.assertEqual([lead.model_dump(mode="json") for lead in loaded], expected)
        self.assertEqual(LeadJsonService(path).load()[0].lead_id, self.lead.lead_id)
        self.assertEqual(path.read_bytes(), original_bytes)
        saved = self.store.save(loaded)
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), expected)
        # Retired compatibility keys do not weaken validation of other fields.
        legacy[0]["enrichment"]["unexpected"] = "bad"
        with self.assertRaises(ValidationError):
            LeadResult.model_validate(legacy[0])

    def test_empty_results_are_a_valid_empty_json_list(self):
        path = self.store.save([])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [])
        self.assertEqual(self.store.load(path.parent.name), [])

    def test_invalid_batch_is_rejected_before_any_artifact_is_created(self):
        with self.assertRaises(ValidationError):
            self.store.save([self.lead, {"lead_id": "bad"}])
        self.assertFalse(self.root.exists())

    def test_modified_model_is_revalidated_before_writing(self):
        self.lead.enrichment.services = "not a list"
        with self.assertRaises(ValidationError):
            self.store.save([self.lead])
        self.assertFalse(self.root.exists())

    def test_publish_failure_leaves_no_partial_artifact(self):
        with patch("app.services.lead_results.Path.rename", side_effect=OSError("fixture disk error")):
            with self.assertRaisesRegex(OSError, "fixture disk error"):
                self.store.save([self.lead])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_concurrent_runs_do_not_overwrite_each_other(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            paths = list(executor.map(lambda _: self.store.save([self.lead]), range(4)))
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual(len(list(self.root.iterdir())), 4)
        for path in paths:
            self.assertEqual(self.store.load(path.parent.name)[0].model_dump(mode="json"),
                             self.lead.model_dump(mode="json"))

    def test_load_rejects_caller_paths_and_reports_missing_runs(self):
        for run_id in ["../outside", "..\\outside", "leads.json", "C:\\outside\\leads.json"]:
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.store.load(run_id)
        with self.assertRaises(FileNotFoundError):
            self.store.load(uuid4())

    def test_load_validates_corrupt_or_invalid_artifacts(self):
        path = self.store.save([self.lead])
        for contents in ["{broken", '[{"lead_id":"bad"}]']:
            path.write_text(contents, encoding="utf-8")
            with self.subTest(contents=contents), self.assertRaises(ValidationError):
                self.store.load(path.parent.name)

    def test_excluded_attributions_are_not_saved(self):
        for field in ["api_key", "password", "Authorization", "X-Goog-Api-Key"]:
            self.lead.discovery.source_attributions = [{field: "fixture-secret"}]
            path = self.store.save([self.lead])
            self.assertNotIn("source_attributions", path.read_text(encoding="utf-8"))
            self.assertNotIn("fixture-secret", path.read_text(encoding="utf-8"))

    def test_credentials_in_urls_are_rejected_without_writing(self):
        for url in ["https://user:fixture-secret@fixture.example/",
                    "https://fixture.example/?api_key=fixture-secret"]:
            self.lead.discovery.website = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "credential"):
                self.store.save([self.lead])
            self.assertFalse(self.root.exists())

    def test_loading_an_artifact_with_credentials_is_rejected(self):
        path = self.store.save([self.lead])
        data = json.loads(path.read_text(encoding="utf-8"))
        data[0]["discovery"]["website"] = "https://fixture.example/?password=fixture-secret"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "credential"):
            self.store.load(path.parent.name)


class PersistencePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "leads"
        self.store = LeadResultStore(self.root)

    async def test_only_final_filtered_ranked_limited_leads_are_saved(self):
        service, _, _, enrichment, scoring = pipeline([0] * 30 + list(range(80, 100)))
        service.result_store = self.store
        result = await service.run("agency", "Nashik", limit=10, priority="high")
        stored = self.store.load(result.result_path.parent.name)
        self.assertEqual([lead.lead_id for lead in stored],
                         [f"lead_{i:03d}" for i in range(49, 39, -1)])
        self.assertEqual([lead.model_dump(mode="json") for lead in stored],
                         [canonical_lead_output(lead).model_dump(mode="json") for lead in result.leads])
        self.assertEqual(enrichment.enrich.await_count, 50)
        self.assertEqual(scoring.score.call_count, 50)

    async def test_no_results_are_persisted_without_enrichment_or_scoring(self):
        service, _, _, enrichment, scoring = pipeline([])
        service.result_store = self.store
        result = await service.run("agency", "Nashik")
        self.assertEqual(self.store.load(result.result_path.parent.name), [])
        enrichment.enrich.assert_not_awaited()
        scoring.score.assert_not_called()

    async def test_failed_pipeline_does_not_create_result_files(self):
        service, *_, scoring = pipeline([95])
        service.result_store = self.store
        scoring.score.side_effect = RuntimeError("fixture scoring failure")
        with self.assertRaisesRegex(RuntimeError, "fixture scoring failure"):
            await service.run("agency", "Nashik")
        self.assertFalse(self.root.exists())

    async def test_raw_metadata_and_environment_credentials_are_not_saved(self):
        service, _, _, enrichment, _ = pipeline([95])
        service.result_store = self.store
        raw = enriched(business(0))
        raw["api_key"] = "fixture-secret"
        raw["extraction_metadata"] = {"password": "fixture-secret"}
        raw["website_analysis"]["website_content"] = [{"main_text": "fixture-secret"}]
        enrichment.enrich.side_effect = None
        enrichment.enrich.return_value = raw
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "fixture-secret"}):
            result = await service.run("agency", "Nashik")
        self.assertNotIn("fixture-secret", result.result_path.read_text(encoding="utf-8"))
        self.assertEqual(self.store.load(result.result_path.parent.name)[0].scoring.lead_score, 95)

    async def test_api_returns_the_same_canonical_records_written_to_disk(self):
        record = business(0, website="http://fixture.example", rating=4.8, review_count=120)
        service, *_ = pipeline([None], records=[record])
        service.result_store = self.store
        crawler = SimpleNamespace(crawl=AsyncMock(side_effect=crawled_website))
        set_enrichment(service, LeadPipeline(crawler=crawler))
        service.scorer = score_lead
        service.scorer = Mock(wraps=service.scorer)
        with patch.object(app.state, "lead_discovery_service", service, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/leads/discover", json={
                    "query": "agency", "location": "Nashik", "limit": 1, "priority": "high",
                })
        self.assertEqual(response.status_code, 200)
        files = list(self.root.glob("*/leads.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text(encoding="utf-8")), response.json()["leads"])
        output = response.json()["leads"][0]
        self.assertFalse({"sub_category", "source_ref"} & output["discovery"].keys())
        self.assertFalse({"final_url", "operating_hours"} & output["enrichment"].keys())
        self.assertEqual(output["discovery"]["source_url"], record.source_url)
        self.assertEqual(output["discovery"]["website"], record.website)
        self.assertEqual(output["enrichment"]["website_url"], record.website)
        self.assertEqual(output["enrichment"]["website_status"], "active")
        self.assertEqual(response.json()["leads"][0]["scoring"], {
            "lead_score": 86.7, "priority": "High", "qualification_status": "Qualified",
        })
        crawler.crawl.assert_awaited_once()
        service.scorer.assert_called_once()

    async def test_low_priority_api_preserves_qualification_in_response_and_storage(self):
        service, *_ = pipeline([50])
        service.result_store = self.store
        with patch.object(app.state, "lead_discovery_service", service, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/leads/discover", json={
                    "query": "agency", "location": "Nashik", "limit": 1,
                    "priority": "low",
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["leads"][0]["scoring"]["qualification_status"],
                         "Needs Review")
        path = next(self.root.glob("*/leads.json"))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), response.json()["leads"])
        self.assertEqual(self.store.load(path.parent.name)[0].scoring.qualification_status, "Needs Review")

    async def test_disk_failure_is_a_server_error_without_exposing_details(self):
        service, *_ = pipeline([95])
        service.result_store = self.store
        with patch.object(self.store, "save", side_effect=OSError("fixture-secret")):
            with patch.object(app.state, "lead_discovery_service", service, create=True):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post("/api/v1/leads/discover", json={
                        "query": "agency", "location": "Nashik", "limit": 1, "priority": "high",
                    })
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("fixture-secret", response.text)
        self.assertIn("Failed to persist final lead results.", response.text)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
