"""Restored Voice behavior and proposal boundary; all provider requests are mocked."""

import gc
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from omnidimension import APIError
from pydantic import ValidationError

from app.app import app
from app.core.config import Settings
from app.integrations.omnidimension import OmniDimensionDispatchProvider
from app.models.leads import LeadFileError, normalize_indian_mobile
from app.schemas.calling_eligibility import ConsentRecordInput
from app.schemas.outreach import VoiceCallRequest
from app.schemas.proposal import ProposalResult
from app.services.calling_eligibility import CallingEligibilityStore
from app.agents.lead_pipeline.pipeline import canonical_lead_output
from app.services.lead_results import LeadResultStore
from app.services.leads import LeadJsonService
from app.services.outreach_repository import DispatchLedger
from app.services.proposals import ProposalFileError, ProposalJsonService
from app.services.voice_service import VoiceCallService
from tests.test_lead_discovery import business, enriched


PHONE = "+919876543210"
PURPOSE = "commercial_sales_call"
AGENT_ID = 261506


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Reference stores rely on connection finalization; release cycles before
        # removing SQLite files on Windows without changing runtime behavior.
        self.addCleanup(gc.collect)
        self.root = Path(self.temp.name)
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("Real provider calls forbidden"))
        network.start()
        self.addCleanup(network.stop)
        raw = enriched(business(0, phone="98765 43210", category="Retail", address="Fixture City"))
        raw["lead_scoring"] = {"lead_score": 95, "priority": "High", "qualification_status": "Qualified"}
        self.lead = canonical_lead_output(raw)
        self.leads = self.root / "leads"
        self.lead_path = LeadResultStore(self.leads).save([self.lead])
        self.database = self.root / "calls" / "calling_eligibility.sqlite3"
        self.store = CallingEligibilityStore(self.database)
        self.ledger = DispatchLedger(self.database)
        self.consent()
        self.provider = Mock()
        self.provider.get_agent.return_value = {"json": {
            "id": AGENT_ID, "bot_call_type": "Outgoing",
            "languages": ["English (India)", "Hindi", "Marathi"],
        }}
        self.provider.dispatch_call.return_value = {"json": {
            "success": True, "status": "dispatched", "requestId": "fixture-provider-id",
        }}
        self.factory = Mock(return_value=self.provider)
        self.proposals = self.root / "proposals"
        self.proposal_loader = ProposalJsonService(self.proposals)
        self.key = uuid4()

    def consent(self, **changes):
        values = dict(
            lead_id=self.lead.lead_id, phone_number=PHONE, consent_status="verified",
            consent_scope=PURPOSE, consent_source="test fixture", evidence_reference="fixture:permission",
            verified_at=datetime.now(timezone.utc), verified_by="fixture-reviewer",
        )
        values.update(changes)
        self.store.save_consent(ConsentRecordInput(**values))

    def service(self, **changes):
        values = dict(
            lead_service=LeadJsonService(self.leads), eligibility_store=self.store,
            ledger=self.ledger, provider_factory=self.factory, agent_id=AGENT_ID,
            enabled=True, purpose=PURPOSE, represented_business_name="Verified Caller",
            represented_business_identity_verified=True, proposal_service=self.proposal_loader,
        )
        values.update(changes)
        return VoiceCallService(**values)

    def proposal(self, **changes):
        # Synthetic boundary fixture, never a generated or production proposal.
        values = {"lead_id": self.lead.lead_id, "proposed_service": "Fixture service",
                  "approved_product_facts": "Fixture approved facts", "approved_pricing": "Fixture price"}
        values.update(changes)
        path = self.proposals / self.lead.lead_id / "proposal.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values), encoding="utf-8")
        return path

    def test_valid_lead_preserves_context_payload_and_original_phone(self):
        original = self.lead_path.read_bytes()
        result = self.service().run(self.lead.lead_id, "98765 43210", self.key)
        self.assertEqual(result.status, "dispatched")
        self.assertEqual(result.provider_request_id, "fixture-provider-id")
        self.provider.dispatch_call.assert_called_once_with(
            agent_id=AGENT_ID, to_number=PHONE, call_context={
                "lead_business_name": "Fixture Agency 0", "business_category": "Retail",
                "business_location": "Fixture City", "verified_business_name": "Verified Caller",
                "contact_basis_status": "verified",
            },
        )
        self.assertEqual(self.lead_path.read_bytes(), original)
        self.assertEqual(LeadJsonService(self.leads).load()[0].phone_numbers[0].original_value, "98765 43210")

    def test_indian_mobile_normalization_and_restrictions(self):
        for value in ["9876543210", "+91 98765 43210", "91-98765-43210", "+91 (98765) 43210"]:
            self.assertEqual(normalize_indian_mobile(value), PHONE)
        for value in ["", "12345", "+14155552671", "5123456789", "9876543210 ext 2", "(98765) 43210"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_indian_mobile(value)

    def test_missing_lead_and_invalid_or_missing_phone_do_not_dispatch(self):
        for lead_id, phone, reason in [
            ("missing", PHONE, "lead_not_found"),
            (self.lead.lead_id, "", "phone_invalid"),
            (self.lead.lead_id, "12345", "phone_invalid"),
            (self.lead.lead_id, "+919876543211", "phone_not_associated_with_lead"),
        ]:
            result = self.service().run(lead_id, phone, uuid4())
            self.assertEqual(result.reason_codes, [reason])
        self.factory.assert_not_called()

    def test_missing_phone_in_lead_remains_unassociated(self):
        self.lead.discovery.phone = None
        self.lead.enrichment.phone_numbers = []
        self.lead_path.write_text(json.dumps([self.lead.model_dump(mode="json")]), encoding="utf-8")
        result = self.service().run(self.lead.lead_id, PHONE, self.key)
        self.assertEqual(result.reason_codes, ["phone_not_associated_with_lead"])
        self.factory.assert_not_called()

    def test_unknown_revoked_expired_and_wrong_scope_consent_are_preserved(self):
        for changes, reason in [
            ({"consent_status": "unknown"}, "consent_unknown"),
            ({"consent_status": "revoked", "revoked_at": datetime.now(timezone.utc)}, "consent_revoked"),
            ({"expiry_at": datetime.now(timezone.utc) - timedelta(days=1)}, "consent_expired"),
            ({"consent_scope": "different-purpose"}, "consent_purpose_mismatch"),
        ]:
            self.consent(**changes)
            result = self.service().run(self.lead.lead_id, PHONE, uuid4())
            self.assertIn(reason, result.reason_codes)
        self.factory.assert_not_called()

    def test_unqualified_lead_is_blocked(self):
        self.lead.scoring.qualification_status = "Needs Review"
        self.lead_path.write_text(json.dumps([self.lead.model_dump(mode="json")]), encoding="utf-8")
        result = self.service().run(self.lead.lead_id, PHONE, self.key)
        self.assertIn("lead_not_qualified", result.reason_codes)
        self.factory.assert_not_called()

    def test_dry_run_preserves_order_and_never_loads_proposal_or_provider(self):
        loader = Mock()
        result = self.service(enabled=False, proposal_service=loader,
                              represented_business_identity_verified=False).run(self.lead.lead_id, PHONE, self.key)
        self.assertEqual(result.status, "dry_run")
        self.assertTrue(result.eligible)
        loader.load.assert_not_called()
        self.factory.assert_not_called()
        self.assertIsNone(self.ledger.lookup(self.key))

    def test_identity_agent_and_language_checks_are_preserved(self):
        for changes, reason in [
            ({"agent_id": None}, "outbound_agent_not_configured"),
            ({"represented_business_identity_verified": False}, "represented_business_identity_unverified"),
            ({"represented_business_name": None}, "represented_business_identity_unverified"),
        ]:
            self.assertEqual(self.service(**changes).run(self.lead.lead_id, PHONE, uuid4()).reason_codes, [reason])
        self.factory.assert_not_called()
        self.provider.get_agent.return_value["json"]["bot_call_type"] = "Incoming"
        self.assertEqual(self.service().run(self.lead.lead_id, PHONE, uuid4()).reason_codes,
                         ["configured_agent_is_not_outbound"])
        self.provider.get_agent.return_value["json"]["bot_call_type"] = "Outgoing"
        self.provider.get_agent.return_value["json"]["languages"] = ["English (India)"]
        self.assertEqual(self.service().run(self.lead.lead_id, PHONE, uuid4()).reason_codes, ["agent_languages_unverified"])
        self.provider.dispatch_call.assert_not_called()

    def test_proposal_is_associated_with_lead_and_uses_only_declared_context_fields(self):
        path = self.proposal(business_context="Fixture lead background")
        before = path.read_bytes()
        loaded = self.proposal_loader.load(self.lead.lead_id)
        self.assertEqual(loaded.lead_id, self.lead.lead_id)
        result = self.service().run(self.lead.lead_id, PHONE, self.key)
        self.assertEqual(result.status, "dispatched")
        context = self.provider.dispatch_call.call_args.kwargs["call_context"]
        self.assertEqual(context["proposed_service"], "Fixture service")
        self.assertEqual(context["approved_product_facts"], "Fixture approved facts")
        self.assertEqual(context["approved_pricing"], "Fixture price")
        self.assertEqual(context["business_context"], "Fixture lead background")
        self.assertEqual(context["verified_business_name"], "Verified Caller")
        self.assertNotIn("proposal", context)
        self.assertNotIn("lead_id", context)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_proposal_preserves_existing_dispatch_without_fabrication(self):
        self.assertIsNone(self.proposal_loader.load(self.lead.lead_id))
        self.assertEqual(self.service().run(self.lead.lead_id, PHONE, self.key).status, "dispatched")
        self.assertFalse(self.proposals.exists())
        self.assertNotIn("proposed_service", self.provider.dispatch_call.call_args.kwargs["call_context"])

    def test_wrong_lead_malformed_or_identity_overriding_proposal_is_blocked(self):
        path = self.proposal(lead_id="another-lead")
        for contents in [path.read_text(), "{broken", json.dumps({
            "lead_id": self.lead.lead_id, "verified_business_name": "Caller-supplied identity",
        })]:
            path.write_text(contents, encoding="utf-8")
            result = self.service().run(self.lead.lead_id, PHONE, uuid4())
            self.assertEqual(result.reason_codes, ["proposal_unavailable"])
        self.factory.assert_not_called()
        self.assertEqual(self.ledger.list_records()[1], 0)

    def test_proposal_path_traversal_is_rejected(self):
        for lead_id in ["..", ".", "../outside", "C:\\outside"]:
            with self.subTest(lead_id=lead_id), self.assertRaises(ProposalFileError):
                self.proposal_loader.load(lead_id)

    def test_proposal_and_call_request_reject_untrusted_input(self):
        with self.assertRaises(ValidationError):
            ProposalResult.model_validate({"lead_id": self.lead.lead_id, "contact_basis_status": "verified"})
        request = {"lead_id": self.lead.lead_id, "phone_number": PHONE, "idempotency_key": str(self.key)}
        for extra in [{"proposal": {}}, {"business_name": "untrusted"}, {"agent_id": 1}, {"call_context": {}}]:
            with self.assertRaises(ValidationError):
                VoiceCallRequest.model_validate(request | extra)

    def test_idempotency_ledger_and_history_keep_existing_semantics(self):
        dispatcher = self.service()
        self.assertEqual(dispatcher.run(self.lead.lead_id, PHONE, self.key).status, "dispatched")
        self.assertEqual(dispatcher.run(self.lead.lead_id, PHONE, self.key).status, "duplicate")
        self.provider.dispatch_call.assert_called_once()
        record = self.ledger.get_record(str(self.key))
        self.assertEqual(record["call_id"], str(self.key))
        self.assertEqual(record["provider_request_id"], "fixture-provider-id")
        self.assertEqual(record["dispatch_status"], "dispatched")
        self.assertEqual(record["call_outcome"], "unknown")
        self.assertTrue(record["provider_accepted"])
        self.assertEqual(DispatchLedger(self.database).list_records()[1], 1)

    def test_concurrent_same_key_dispatches_at_most_once(self):
        barrier = Barrier(2)
        response = self.provider.get_agent.return_value
        def synchronize(_):
            barrier.wait(timeout=5)
            return response
        self.provider.get_agent.side_effect = synchronize
        service = self.service()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(service.run, self.lead.lead_id, PHONE, self.key) for _ in range(2)]
            statuses = [future.result(timeout=10).status.value for future in futures]
        self.assertEqual(sorted(statuses), ["dispatched", "duplicate"])
        self.provider.dispatch_call.assert_called_once()

    def test_error_and_uncertain_outcomes_are_not_retried_or_exposed(self):
        for error, status in [(APIError(503, "private-provider-body"), "provider_error"),
                              (APIError(0, "private-provider-body"), "uncertain"),
                              (TimeoutError("private-provider-body"), "uncertain")]:
            self.provider.dispatch_call.side_effect = error
            key = uuid4()
            service = self.service()
            first = service.run(self.lead.lead_id, PHONE, key)
            self.assertEqual(first.status, status)
            self.assertNotIn("private-provider-body", first.model_dump_json())
            self.assertEqual(service.run(self.lead.lead_id, PHONE, key).status, "duplicate")
        self.assertEqual(self.provider.dispatch_call.call_count, 3)

    def test_ambiguous_provider_success_remains_uncertain(self):
        self.provider.dispatch_call.return_value = {"json": {"success": True}}
        result = self.service().run(self.lead.lead_id, PHONE, self.key)
        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.provider_request_id)
        self.assertEqual(self.ledger.lookup(self.key)[2], "uncertain")

    def test_consent_is_rechecked_after_provider_agent_verification(self):
        response = self.provider.get_agent.return_value
        def revoke(_):
            self.consent(consent_status="revoked", revoked_at=datetime.now(timezone.utc))
            return response
        self.provider.get_agent.side_effect = revoke
        result = self.service().run(self.lead.lead_id, PHONE, self.key)
        self.assertIn("consent_revoked", result.reason_codes)
        self.provider.dispatch_call.assert_not_called()
        self.assertEqual(self.ledger.lookup(self.key)[2], "blocked")

    def test_canonical_and_legacy_leads_prepare_identically(self):
        canonical = LeadJsonService(self.lead_path).load()[0]
        path = self.root / "legacy.json"
        path.write_text(json.dumps([{
            "lead_id": self.lead.lead_id, "business": self.lead.discovery.model_dump(mode="json"),
            "contacts": self.lead.enrichment.model_dump(mode="json"),
            "lead_scoring": self.lead.scoring.model_dump(mode="json"),
        }]), encoding="utf-8")
        self.assertEqual(LeadJsonService(path).load()[0], canonical)

    def test_directory_loading_uses_latest_lead_and_ignores_staging(self):
        self.lead.discovery.business_name = "Updated Fixture"
        path = LeadResultStore(self.leads).save([self.lead])
        import os
        old_time = self.lead_path.stat().st_mtime_ns
        os.utime(path, ns=(old_time + 1_000_000_000, old_time + 1_000_000_000))
        staging = self.leads / ".run-incomplete"
        staging.mkdir()
        (staging / "leads.json").write_text("{broken", encoding="utf-8")
        prepared = LeadJsonService(self.leads).load()
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0].business_name, "Updated Fixture")

    def test_invalid_lead_artifact_fails_closed(self):
        self.lead_path.write_text('[{"lead_id":"bad","discovery":{}}]', encoding="utf-8")
        with self.assertRaises(LeadFileError):
            LeadJsonService(self.lead_path).load()
        self.assertEqual(self.service().run(self.lead.lead_id, PHONE, self.key).reason_codes,
                         ["lead_source_unavailable"])
        self.factory.assert_not_called()

    def test_omnidimension_adapter_forwards_existing_sdk_arguments(self):
        with patch("app.integrations.omnidimension.Client") as client:
            provider = OmniDimensionDispatchProvider("fixture-sdk-credential")
            context = {"lead_business_name": "Fixture"}
            provider.dispatch_call(AGENT_ID, PHONE, context)
            client.return_value.call.dispatch_call.assert_called_once_with(
                agent_id=AGENT_ID, to_number=PHONE, call_context=context,
            )
            provider.get_agent(AGENT_ID)
            client.return_value.agent.get.assert_called_once_with(AGENT_ID)

    def test_authenticated_api_dispatch_history_and_idempotency(self):
        token = "a" * 40
        settings = Settings(_env_file=None, lead_json_path=str(self.leads),
                            eligibility_db_path=str(self.database), proposal_root=str(self.proposals),
                            eligibility_admin_token=token, outbound_calls_enabled=True,
                            outbound_represented_business_name="Verified Caller",
                            outbound_represented_business_identity_verified=True)
        with patch("app.services.voice_service.get_settings", return_value=settings), \
             patch("app.api.v1.calling_eligibility.get_settings", return_value=settings), \
             patch("app.api.v1.calls.get_settings", return_value=settings), \
             patch("app.services.voice_service.OmniDimensionDispatchProvider", return_value=self.provider):
            with TestClient(app) as client:
                request = {"lead_id": self.lead.lead_id, "phone_number": PHONE, "idempotency_key": str(self.key)}
                headers = {"Authorization": "Bearer " + token}
                self.assertEqual(client.post("/api/v1/calls/dispatch", json=request).status_code, 401)
                self.assertEqual(client.post("/api/v1/calls/dispatch", json={"lead_id": self.lead.lead_id}, headers=headers).status_code, 422)
                consent = {"lead_id": self.lead.lead_id, "phone_number": PHONE,
                           "consent_status": "verified", "consent_scope": PURPOSE,
                           "consent_source": "test fixture", "evidence_reference": "fixture:permission"}
                self.assertEqual(client.put("/api/v1/calling-eligibility/consent", json=consent).status_code, 401)
                recorded = client.put("/api/v1/calling-eligibility/consent", json=consent, headers=headers)
                self.assertEqual(recorded.status_code, 200)
                self.assertEqual(recorded.json()["verified_by"], "eligibility-admin")
                self.assertNotIn("evidence_reference", recorded.json())
                eligibility = client.get("/api/v1/calling-eligibility/" + self.lead.lead_id,
                                         params={"phone_number": PHONE}, headers=headers)
                self.assertEqual(eligibility.status_code, 200)
                self.assertTrue(eligibility.json()["eligible"])
                result = client.post("/api/v1/calls/dispatch", json=request, headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["status"], "dispatched")
                duplicate = client.post("/api/v1/calls/dispatch", json=request, headers=headers)
                self.assertEqual(duplicate.status_code, 200)
                self.assertEqual(duplicate.json()["status"], "duplicate")
                removed = client.post("/api/outreach/voice/call", json=request, headers=headers)
                self.assertEqual(removed.status_code, 404)
                history = client.get("/api/v1/calls", headers=headers)
                self.assertEqual(history.status_code, 200)
                self.assertEqual(history.json()["total"], 1)
                detail = client.get("/api/v1/calls/" + str(self.key), headers=headers)
                self.assertEqual(detail.json()["call_outcome"], "unknown")
        self.provider.dispatch_call.assert_called_once()

    def test_configuration_keeps_dispatch_disabled_by_default_and_paths_in_backend(self):
        settings = Settings(_env_file=None)
        self.assertFalse(settings.outbound_calls_enabled)
        self.assertEqual(Path(settings.lead_json_path), Path.cwd() / "app/results/leads")
        self.assertEqual(Path(settings.eligibility_db_path), Path.cwd() / "app/results/calls/calling_eligibility.sqlite3")


if __name__ == "__main__":
    unittest.main()
