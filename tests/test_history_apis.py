"""Stored lead search and email history using real local stores, no providers."""

import json
import os
import sqlite3
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from app.app import app
from app.core.config import EmailSettings
from app.schemas.email import EmailDraft
from app.services.email_results import EmailResultStore
from app.services.email_service import EmailService, get_email_service
from app.services.lead_results import LeadResultStore
from app.agents.lead_pipeline.pipeline import canonical_lead_output
from tests.test_lead_discovery import business, enriched


ADMIN = "history-admin-" + "a" * 32
REVIEWER = "history-reviewer-" + "r" * 32


class HistoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = EmailSettings(
            _env_file=None, lead_json_path=str(self.root / "leads"),
            email_db_path=str(self.root / "emails.sqlite3"),
            proposal_root=str(self.root / "proposals"),
            eligibility_admin_token=ADMIN, eligibility_reviewer_token=REVIEWER,
        )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in ["app.api.v1.leads", "app.api.v1.calling_eligibility"]:
            self.stack.enter_context(patch(module + ".get_settings", return_value=self.settings))
        self.provider = Mock()
        self.service = EmailService(self.settings, provider=self.provider)
        app.dependency_overrides[get_email_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.pop, get_email_service)
        self.forbidden = []
        for target in [
            "app.agents.lead_pipeline.pipeline.LeadPipeline.run",
            "app.agents.lead_pipeline.pipeline.LeadPipeline._enrich",
            "app.agents.lead_pipeline.pipeline.score_lead",
            "app.integrations.google_places.GooglePlacesClient.search",
            "app.integrations.maps_scraper.GoogleMapsBrowserDiscovery.search",
            "app.integrations.website_fetcher.WebsiteCrawler.crawl",
        ]:
            guard = self.stack.enter_context(patch(target, side_effect=AssertionError("Read triggered pipeline")))
            self.forbidden.append(guard)
        for name in ["preview", "approve", "queue", "send"]:
            guard = self.stack.enter_context(patch.object(
                self.service, name, side_effect=AssertionError("Read triggered email workflow"),
            ))
            self.forbidden.append(guard)
        self.stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.store = LeadResultStore(self.settings.lead_json_path)

    async def asyncTearDown(self):
        for guard in self.forbidden:
            guard.assert_not_called()
        self.provider.send.assert_not_called()

    async def get(self, path, params=None, token=ADMIN):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return await self.client.get(path, params=params, headers=headers)

    def lead(self, index, *, category="Clinic", priority="High", qualification="Qualified", **changes):
        record = business(index, category=category, phone="+91 98765 43210",
                          website="https://fixture.example/", **changes)
        raw = enriched(record)
        raw["contacts"]["phone_numbers"] = ["+919112223334"]
        raw["lead_scoring"] = {"lead_score": 90, "priority": priority,
                               "qualification_status": qualification}
        return canonical_lead_output(raw)

    async def test_leads_missing_and_empty_storage(self):
        for create in [False, True]:
            if create:
                self.store.save([])
            response = await self.get("/api/v1/leads")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"items": [], "total": 0, "limit": 25, "offset": 0})

    async def test_lead_search_supported_fields_and_no_match(self):
        lead = self.lead(0, business_name="Unique Practice", address="Central Road")
        path = self.store.save([lead])
        original = path.read_bytes()
        for query in ["unique", " CENTRAL ", "clinic", "98765", "fixture.example", "9112223334"]:
            with self.subTest(query=query):
                response = await self.get("/api/v1/leads", {"q": query}, token=REVIEWER)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["items"], [lead.model_dump(mode="json")])
                self.assertEqual(response.json()["total"], 1)
        response = await self.get("/api/v1/leads", {"q": "no such business"})
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["total"], 0)
        self.assertEqual(path.read_bytes(), original)

    async def test_lead_filters_combine_before_pagination(self):
        leads = [self.lead(0), self.lead(1, category="Retail", priority="Low", qualification="Not Qualified"),
                 self.lead(2, priority="Medium", qualification="Needs Review")]
        self.store.save(leads)
        for params, expected in [
            ({"category": " cLiNiC "}, [0, 2]),
            ({"priority": "Low"}, [1]),
            ({"qualification_status": "Needs Review"}, [2]),
            ({"category": "Clinic", "priority": "High", "qualification_status": "Qualified"}, [0]),
            ({"category": "Retail", "priority": "High"}, []),
        ]:
            with self.subTest(params=params):
                response = await self.get("/api/v1/leads", params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([item["lead_id"] for item in response.json()["items"]],
                                 [leads[index].lead_id for index in expected])
                self.assertEqual(response.json()["total"], len(expected))
        response = await self.get("/api/v1/leads", {"category": "Clinic", "limit": 1, "offset": 1})
        self.assertEqual(response.json(), {"items": [leads[2].model_dump(mode="json")],
                                          "total": 2, "limit": 1, "offset": 1})
        response = await self.get("/api/v1/leads", {"offset": 20})
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["total"], 3)

    async def test_newest_snapshot_wins_before_filtering_and_staging_is_ignored(self):
        old = self.lead(0)
        old_path = self.store.save([old, self.lead(1)])
        new = self.lead(0, category="Retail")
        new_path = self.store.save([new, self.lead(2)])
        os.utime(old_path, ns=(1_000_000_000, 1_000_000_000))
        os.utime(new_path, ns=(2_000_000_000, 2_000_000_000))
        staging = self.store.root / ".run-incomplete" / "leads.json"
        staging.parent.mkdir()
        staging.write_text("broken", encoding="utf-8")
        response = await self.get("/api/v1/leads")
        self.assertEqual(response.json()["total"], 3)
        self.assertEqual([lead["lead_id"] for lead in response.json()["items"]], [new.lead_id, "lead_002", "lead_001"])
        self.assertEqual(response.json()["items"][0]["discovery"]["category"], "Retail")
        response = await self.get("/api/v1/leads", {"category": "Clinic"})
        self.assertEqual(response.json()["total"], 2)

    async def test_single_legacy_canonical_file_omits_internal_fields(self):
        lead = self.lead(0)
        path = self.store.save([lead])
        payload = [lead.model_dump(mode="json")]
        payload[0]["discovery"].update(source_ref="private", sub_category="private",
                                      source_attributions=[{"api_key": "fixture-secret"}])
        payload[0]["enrichment"].update(final_url="https://fixture.example/", operating_hours={})
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.settings.lead_json_path = str(path)
        response = await self.get("/api/v1/leads")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [lead.model_dump(mode="json")])
        self.assertNotIn("fixture-secret", response.text)

    async def test_invalid_lead_storage_has_safe_error(self):
        path = self.store.save([self.lead(0)])
        for payload in ["{fixture-secret", '[{"lead_id":"fixture-secret"}]']:
            path.write_text(payload, encoding="utf-8")
            response = await self.get("/api/v1/leads")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["detail"], "Lead source is unavailable.")
            self.assertNotIn("fixture-secret", response.text)
        with patch.object(LeadResultStore, "list_records", side_effect=OSError("fixture-secret")):
            self.assertEqual((await self.get("/api/v1/leads")).status_code, 503)

    async def test_lead_query_validation(self):
        for params in [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 1000001},
                       {"limit": "bad"}, {"priority": "mid"}, {"qualification_status": "wrong"},
                       {"q": ""}, {"q": "x" * 257}, {"category": "x" * 257}]:
            with self.subTest(params=params):
                self.assertEqual((await self.get("/api/v1/leads", params)).status_code, 422)

    def email_records(self):
        store = EmailResultStore(self.settings.email_db_path)
        records = []
        for index, status in enumerate(["pending", "sending", "sent", "failed", "uncertain"]):
            draft = EmailDraft(lead_id=f"lead_{index}", business_name=f"Fixture {index}",
                               recipient="recipient@fixture.example", sender="sender@fixture.example",
                               proposal_file=f"lead_{index}/proposal.json", subject="Fixture", body="Fixture",
                               review_id=f"{index:064x}")
            record, created = store.enqueue(draft)
            self.assertTrue(created)
            if status != "pending":
                store.claim(record.email_id)
            if status in {"sent", "failed", "uncertain"}:
                store.finish(record.email_id, status,
                             error="email_provider_rejected" if status == "failed" else
                                   "email_provider_outcome_uncertain" if status == "uncertain" else None,
                             message_id="<fixture@fixture.example>" if status == "sent" else None)
            with closing(sqlite3.connect(self.settings.email_db_path)) as db, db:
                db.execute("UPDATE email_results SET created_at=? WHERE email_id=?",
                           (f"2026-10-09T0{index}:00:00+00:00", str(record.email_id)))
            records.append(store.get(record.email_id))
        return records

    async def test_empty_email_history(self):
        response = await self.get("/api/v1/emails")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"emails": [], "total": 0, "limit": 25, "offset": 0})

    async def test_email_history_uses_existing_store_and_keeps_status_meanings(self):
        records = self.email_records()
        with patch.object(self.service.store, "list_records", wraps=self.service.store.list_records) as listing:
            response = await self.get("/api/v1/emails")
        self.assertEqual(response.status_code, 200)
        listing.assert_called_once_with(status=None, limit=25, offset=0)
        self.assertEqual(response.json()["total"], 5)
        self.assertEqual(response.json()["emails"], [record.model_dump(mode="json") for record in reversed(records)])
        self.assertEqual([item["status"] for item in response.json()["emails"]],
                         ["uncertain", "failed", "sent", "sending", "pending"])
        for item in response.json()["emails"]:
            self.assertEqual(item["sent_at"] is not None, item["status"] == "sent")
            self.assertNotIn("delivered", item)

    async def test_email_status_filters_pagination_and_totals(self):
        records = self.email_records()
        for record in records:
            response = await self.get("/api/v1/emails", {"status": record.status})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual(response.json()["emails"], [record.model_dump(mode="json")])
        response = await self.get("/api/v1/emails", {"limit": 2, "offset": 1})
        self.assertEqual(response.json(), {"emails": [records[i].model_dump(mode="json") for i in [3, 2]],
                                          "total": 5, "limit": 2, "offset": 1})
        response = await self.get("/api/v1/emails", {"status": "sent", "offset": 20})
        self.assertEqual(response.json()["emails"], [])
        self.assertEqual(response.json()["total"], 1)

    async def test_email_no_match_and_timestamp_ties_are_stable(self):
        records = self.email_records()
        with closing(sqlite3.connect(self.settings.email_db_path)) as db, db:
            db.execute("UPDATE email_results SET created_at='2026-10-09T00:00:00+00:00'")
        response = await self.get("/api/v1/emails")
        self.assertEqual([item["email_id"] for item in response.json()["emails"]],
                         sorted(str(record.email_id) for record in records))
        empty_store = EmailResultStore(self.root / "empty.sqlite3")
        empty_store.record_failure("fixture", "proposal_not_found")
        self.service.store = empty_store
        response = await self.get("/api/v1/emails", {"status": "sent"})
        self.assertEqual(response.json()["total"], 0)
        self.assertEqual(response.json()["emails"], [])

    async def test_email_detail_contract_and_not_found_are_unchanged(self):
        for record in self.email_records():
            response = await self.get(f"/api/v1/emails/{record.email_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), record.model_dump(mode="json"))
        self.assertEqual((await self.get(f"/api/v1/emails/{uuid4()}")).status_code, 404)
        self.assertEqual((await self.get("/api/v1/emails/not-a-uuid")).status_code, 422)

    async def test_email_history_redacts_unknown_errors_without_modifying_storage(self):
        secret = "SMTP password=fixture-secret api_key=fixture-token"
        record = self.service.store.record_failure("fixture", secret)
        response = await self.get("/api/v1/emails")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["emails"][0]["error"], "email_error_details_unavailable")
        self.assertNotIn("fixture-secret", response.text)
        self.assertNotIn("fixture-token", response.text)
        self.assertEqual(self.service.store.get(record.email_id).error, secret)

    async def test_email_storage_error_is_safe(self):
        with patch.object(self.service.store, "list_records", side_effect=sqlite3.OperationalError("fixture-secret")):
            response = await self.get("/api/v1/emails")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], {"code": "email_history_unavailable"})
        self.assertNotIn("fixture-secret", response.text)

    async def test_email_query_validation(self):
        for params in [{"status": "delivered"}, {"limit": 0}, {"limit": 101},
                       {"offset": -1}, {"offset": 1000001}, {"offset": "bad"}]:
            with self.subTest(params=params):
                self.assertEqual((await self.get("/api/v1/emails", params)).status_code, 422)

    async def test_authorization_matches_existing_read_and_email_roles(self):
        for path in ["/api/v1/leads", "/api/v1/emails"]:
            for token in [None, "invalid"]:
                with self.subTest(path=path, token=token):
                    response = await self.get(path, token=token)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual((await self.get("/api/v1/leads", token=REVIEWER)).status_code, 200)
        self.assertEqual((await self.get("/api/v1/emails", token=REVIEWER)).status_code, 401)

    async def test_openapi_documents_typed_history_and_keeps_discovery_contract(self):
        schema = (await self.client.get("/openapi.json")).json()
        for path, response_name in [("/api/v1/leads", "StoredLeadPage"),
                                    ("/api/v1/emails", "EmailHistoryPage")]:
            route = schema["paths"][path]["get"]
            self.assertEqual(route["security"], [{"LeadSutraBearer": []}])
            self.assertEqual(route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                             "#/components/schemas/" + response_name)
        self.assertEqual(set(schema["components"]["schemas"]["LeadDiscoveryRequest"]["properties"]),
                         {"query", "location", "limit", "priority"})
        self.assertIn("post", schema["paths"]["/api/v1/leads/discover"])
        self.assertIn("get", schema["paths"]["/api/v1/emails/{email_id}"])


if __name__ == "__main__":
    unittest.main()