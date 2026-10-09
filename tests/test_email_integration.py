"""Step 7: temporary artifacts, actual SQLite/background tasks, mocked SMTP only."""

import json
import os
import smtplib
import sqlite3
import ssl
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.emails import send
from app.app import app
from app.core.config import EmailSettings, Settings
from app.integrations.smtp import SmtpEmailProvider
from app.schemas.email import EmailApprovalRequest, EmailRequest
from app.services.email_results import EmailResultStore
from app.services.email_service import EmailService, EmailWorkflowError, get_email_service
from app.agents.lead_pipeline.pipeline import canonical_lead_output
from app.services.lead_results import LeadResultStore
from tests.test_lead_discovery import business, enriched


class EmailTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        guard = patch("socket.create_connection", side_effect=AssertionError("Real SMTP network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        self.lead = canonical_lead_output(enriched(business(0, email="listing@fixture.example")))
        self.lead.enrichment.emails = ["hello@fixture.example", "second@fixture.example"]
        self.leads = self.root / "leads"
        self.lead_path = LeadResultStore(self.leads).save([self.lead])
        self.proposal_path = self.root / "proposals" / self.lead.lead_id / "proposal.json"
        self.proposal_path.parent.mkdir(parents=True)
        self.proposal()
        self.settings = EmailSettings(_env_file=None, lead_json_path=str(self.leads),
                                 proposal_root=str(self.root / "proposals"),
                                 email_db_path=str(self.root / "emails" / "emails.sqlite3"),
                                 eligibility_admin_token="a" * 40, eligibility_reviewer_token="r" * 40,
                                 email_sending_enabled=True, smtp_host="smtp.fixture.example",
                                 smtp_username="fixture-sender", smtp_password="fixture-private-password",
                                 smtp_from_address="sender@fixture.example")
        self.provider = Mock()
        self.provider.send.return_value = "<fixture-msg-id@fixture.example>"
        self.service = EmailService(self.settings, provider=self.provider)

    def proposal(self, **changes):
        # Explicitly synthetic contract fixture, outside all production results.
        value = {"lead_id": self.lead.lead_id, "business_context": "Fixture background",
                 "proposed_service": "Fixture service", "approved_product_facts": "Fixture facts",
                 "approved_pricing": "Fixture price"}
        value.update(changes)
        self.proposal_path.write_text(json.dumps(value), encoding="utf-8")

    def save_lead(self):
        self.lead_path.write_text(json.dumps([self.lead.model_dump(mode="json")]), encoding="utf-8")

    def approve(self):
        draft = self.service.preview(self.lead.lead_id)
        return self.service.approve(draft.lead_id, draft.review_id, True, "eligibility-admin")

    def error(self, function, code, status=None):
        with self.assertRaises(EmailWorkflowError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        if status is not None:
            self.assertEqual(caught.exception.status_code, status)
        return caught.exception

    def test_preview_reuses_proposal_and_canonical_lead_without_modifying_files(self):
        before = self.lead_path.read_bytes(), self.proposal_path.read_bytes()
        with patch.object(self.service.proposals, "load", wraps=self.service.proposals.load) as loader:
            draft = self.service.preview(self.lead.lead_id)
            loader.assert_called_once_with(self.lead.lead_id)
        self.assertEqual(draft.recipient, "hello@fixture.example")
        self.assertEqual(draft.business_name, self.lead.discovery.business_name)
        self.assertEqual(draft.subject, "Proposal for Fixture Agency 0")
        self.assertEqual(draft.body, "Business context\nFixture background\n\nProposed service\nFixture service"
                                   "\n\nProduct facts\nFixture facts\n\nPricing\nFixture price")
        self.assertFalse(draft.approved)
        self.assertEqual(before, (self.lead_path.read_bytes(), self.proposal_path.read_bytes()))
        self.provider.send.assert_not_called()

    def test_unapproved_proposal_is_rejected_and_failure_recorded(self):
        error = self.error(lambda: self.service.queue(self.lead.lead_id), "proposal_not_approved", 403)
        self.assertEqual(self.service.result(error.email_id).status, "failed")
        self.provider.send.assert_not_called()

    def test_approval_is_explicit_persistent_and_separate_from_sending(self):
        draft = self.approve()
        reloaded = EmailService(self.settings, provider=self.provider).preview(draft.lead_id)
        self.assertTrue(reloaded.approved)
        self.provider.send.assert_not_called()
        self.service.approve(draft.lead_id, draft.review_id, False, "eligibility-admin")
        self.assertFalse(self.service.preview(draft.lead_id).approved)

    def test_stale_or_forged_review_cannot_be_approved(self):
        draft = self.service.preview(self.lead.lead_id)
        self.proposal(proposed_service="Changed fixture")
        self.error(lambda: self.service.approve(draft.lead_id, draft.review_id, True, "admin"), "email_review_changed", 409)
        self.error(lambda: self.service.approve(draft.lead_id, "0" * 64, True, "admin"), "email_review_changed")
        self.assertFalse(self.service.preview(draft.lead_id).approved)

    def test_missing_proposal_rejects_send_and_records_failure(self):
        self.proposal_path.unlink()
        error = self.error(lambda: self.service.queue(self.lead.lead_id), "proposal_not_found", 404)
        self.assertEqual(self.service.result(error.email_id).error, "proposal_not_found")
        self.provider.send.assert_not_called()

    def test_malformed_mismatched_and_unrecognized_proposal_are_rejected(self):
        for value in ["{broken", json.dumps({"lead_id": "wrong", "proposed_service": "Fixture"}),
                      json.dumps({"lead_id": self.lead.lead_id, "smtp_password": "fixture-private-password"})]:
            self.proposal_path.write_text(value, encoding="utf-8")
            error = self.error(lambda: self.service.queue(self.lead.lead_id), "proposal_invalid", 422)
            self.assertNotIn("fixture-private-password", self.service.result(error.email_id).model_dump_json())
        self.provider.send.assert_not_called()

    def test_empty_proposal_cannot_be_approved(self):
        self.proposal_path.write_text(json.dumps({"lead_id": self.lead.lead_id}), encoding="utf-8")
        self.error(lambda: self.service.preview(self.lead.lead_id), "proposal_empty", 422)

    def test_recipient_is_first_valid_enriched_email_with_listing_fallback(self):
        self.lead.enrichment.emails = ["invalid", "noreply@fixture.example", "second@fixture.example", "hello@fixture.example"]
        self.save_lead()
        self.assertEqual(self.service.preview(self.lead.lead_id).recipient, "second@fixture.example")
        self.lead.enrichment.emails = []
        self.save_lead()
        self.assertEqual(self.service.preview(self.lead.lead_id).recipient, "listing@fixture.example")

    def test_missing_invalid_or_no_email_cannot_send(self):
        for values in [[], ["invalid"], ["victim@fixture.example\r\nBcc: other@fixture.example"], ["noreply@fixture.example"]]:
            self.lead.enrichment.emails = values
            self.lead.discovery.email = None
            self.save_lead()
            error = self.error(lambda: self.service.queue(self.lead.lead_id), "recipient_unavailable", 422)
            self.assertEqual(self.service.result(error.email_id).status, "failed")
        self.provider.send.assert_not_called()

    def test_changed_proposal_recipient_or_sender_invalidates_approval(self):
        self.approve()
        self.proposal(approved_pricing="Changed price")
        self.assertFalse(self.service.preview(self.lead.lead_id).approved)
        self.approve()
        self.lead.enrichment.emails = ["changed@fixture.example"]
        self.save_lead()
        self.assertFalse(self.service.preview(self.lead.lead_id).approved)
        self.approve()
        self.settings.smtp_from_address = "other@fixture.example"
        self.assertFalse(self.service.preview(self.lead.lead_id).approved)

    def test_missing_lead_and_invalid_source_fail_closed(self):
        self.error(lambda: self.service.queue("absent"), "lead_not_found", 404)
        self.lead_path.write_text("{broken", encoding="utf-8")
        self.error(lambda: self.service.queue(self.lead.lead_id), "lead_source_unavailable", 503)
        self.provider.send.assert_not_called()

    def test_configured_canonical_run_file_and_latest_saved_lead_are_reused(self):
        original = self.service.preview(self.lead.lead_id)
        self.settings.lead_json_path = str(self.lead_path)
        self.assertEqual(self.service.preview(self.lead.lead_id), original)
        self.settings.lead_json_path = str(self.leads)
        self.lead.discovery.business_name = "Updated Fixture"
        LeadResultStore(self.leads).save([self.lead])
        self.assertEqual(self.service.preview(self.lead.lead_id).business_name, "Updated Fixture")

    def test_sender_configuration_is_required_and_failure_is_secret_free(self):
        self.approve()
        for field, value in [("smtp_host", None), ("smtp_username", None), ("smtp_password", None)]:
            original = getattr(self.settings, field)
            setattr(self.settings, field, value)
            error = self.error(lambda: self.service.queue(self.lead.lead_id), "email_configuration_unavailable", 503)
            result = self.service.result(error.email_id)
            self.assertEqual(result.status, "failed")
            self.assertNotIn("fixture-private-password", result.model_dump_json())
            setattr(self.settings, field, original)
        self.provider.send.assert_not_called()

    def test_disabled_sending_never_queues_provider_work(self):
        self.approve()
        self.settings.email_sending_enabled = False
        self.error(lambda: self.service.queue(self.lead.lead_id), "email_sending_disabled", 503)
        self.provider.send.assert_not_called()

    def test_invalid_sender_or_business_header_is_rejected(self):
        self.settings.smtp_from_address = "sender@fixture.example\r\nBcc: victim@fixture.example"
        self.error(lambda: self.service.preview(self.lead.lead_id), "email_configuration_unavailable")
        self.settings.smtp_from_address = "sender@fixture.example"
        self.lead.discovery.business_name = "Fixture\r\nBcc: victim@fixture.example"
        self.save_lead()
        self.error(lambda: self.service.preview(self.lead.lead_id), "email_business_name_invalid")

    def test_pending_send_is_deferred_to_fastapi_background_task(self):
        self.approve()
        background = BackgroundTasks()
        result = send(EmailRequest(lead_id=self.lead.lead_id), background, self.service)
        self.assertEqual(result.status, "pending")
        self.assertEqual(len(background.tasks), 1)
        self.provider.send.assert_not_called()
        self.service.send(result.email_id)
        stored = EmailResultStore(self.settings.email_db_path).get(result.email_id)
        self.assertEqual(stored.status, "sent")
        self.assertIsNotNone(stored.sent_at)
        self.assertEqual(stored.message_id, "<fixture-msg-id@fixture.example>")
        message = self.provider.send.call_args.args[0]
        self.assertEqual(message["To"], "hello@fixture.example")
        self.assertEqual(message["From"], "sender@fixture.example")
        self.assertIn("Fixture service", message.get_content())

    def test_duplicate_queue_and_send_do_not_resend(self):
        self.approve()
        first, created = self.service.queue(self.lead.lead_id)
        second, again = self.service.queue(self.lead.lead_id)
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(first.email_id, second.email_id)
        self.service.send(first.email_id)
        self.service.send(first.email_id)
        self.assertFalse(self.service.queue(self.lead.lead_id)[1])
        self.provider.send.assert_called_once()

    def test_concurrent_workers_claim_at_most_once(self):
        self.approve()
        queued, _ = self.service.queue(self.lead.lead_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.service.send, [queued.email_id, queued.email_id]))
        self.provider.send.assert_called_once()

    def test_worker_rechecks_proposal_and_revoked_approval(self):
        for mutate in [lambda: self.proposal(proposed_service="Changed after queue"),
                       lambda: self.service.approve(self.lead.lead_id, draft.review_id, False, "admin")]:
            draft = self.approve()
            queued, _ = self.service.queue(draft.lead_id)
            mutate()
            self.service.send(queued.email_id)
            self.assertEqual(self.service.result(queued.email_id).error, "email_approval_changed")
        self.provider.send.assert_not_called()

    def test_missing_proposal_or_config_at_worker_time_is_recorded(self):
        self.approve()
        queued, _ = self.service.queue(self.lead.lead_id)
        self.proposal_path.unlink()
        self.service.send(queued.email_id)
        self.assertEqual(self.service.result(queued.email_id).error, "proposal_not_found")
        self.proposal(proposed_service="New fixture revision")
        self.approve()
        queued, _ = self.service.queue(self.lead.lead_id)
        self.settings.smtp_password = None
        self.service.send(queued.email_id)
        self.assertEqual(self.service.result(queued.email_id).error, "email_configuration_unavailable")
        self.provider.send.assert_not_called()

    def test_provider_failure_and_uncertainty_are_recorded_without_secrets_or_retry(self):
        for index, error, expected in [(0, smtplib.SMTPAuthenticationError(535, b"fixture-private-password"), "failed"),
                                       (1, TimeoutError("fixture-private-password"), "uncertain"),
                                       (2, smtplib.SMTPServerDisconnected("fixture-private-password"), "uncertain")]:
            self.proposal(proposed_service=f"Fixture revision {index}")
            self.approve()
            self.provider.send.side_effect = error
            queued, _ = self.service.queue(self.lead.lead_id)
            self.service.send(queued.email_id)
            result = self.service.result(queued.email_id)
            self.assertEqual(result.status, expected)
            self.assertIsNone(result.sent_at)
            self.assertIsNone(result.message_id)
            self.assertNotIn("fixture-private-password", result.model_dump_json())
            self.service.send(queued.email_id)
        self.assertEqual(self.provider.send.call_count, 3)

    def test_smtp_uses_verified_starttls_authentication_and_existing_message(self):
        draft = self.approve()
        from app.agents.email.agent import build_message
        message = build_message(draft)
        with patch("app.integrations.smtp.smtplib.SMTP") as smtp:
            connection = smtp.return_value.__enter__.return_value
            connection.send_message.return_value = {}
            SmtpEmailProvider(self.settings).send(message)
            smtp.assert_called_once_with(host="smtp.fixture.example", port=587, timeout=15)
            context = connection.starttls.call_args.kwargs["context"]
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            connection.login.assert_called_once_with("fixture-sender", "fixture-private-password")
            connection.send_message.assert_called_once_with(message)
            self.assertEqual([call[0] for call in connection.mock_calls], ["starttls", "login", "send_message"])

    def test_ssl_and_recipient_refusal_use_standard_smtp_behavior(self):
        from app.agents.email.agent import build_message
        message = build_message(self.approve())
        self.settings.smtp_security = "ssl"
        self.settings.smtp_port = 465
        with patch("app.integrations.smtp.smtplib.SMTP_SSL") as smtp:
            connection = smtp.return_value.__enter__.return_value
            connection.send_message.return_value = {"hello@fixture.example": (550, b"fixture refusal")}
            with self.assertRaises(smtplib.SMTPRecipientsRefused):
                SmtpEmailProvider(self.settings).send(message)
            self.assertEqual(smtp.call_args.kwargs["context"].verify_mode, ssl.CERT_REQUIRED)
            connection.starttls.assert_not_called()

    def test_private_configurations_do_not_share_clients_or_sender_approval(self):
        self.approve()
        other_settings = EmailSettings(_env_file=None, **(self.settings.model_dump() | {
            "smtp_from_address": "other@fixture.example", "smtp_username": "other-user",
            "smtp_password": "other-private-password"}))
        other_provider = Mock()
        other = EmailService(other_settings, provider=other_provider)
        self.assertFalse(other.preview(self.lead.lead_id).approved)
        self.error(lambda: other.queue(self.lead.lead_id), "proposal_not_approved")
        queued, _ = self.service.queue(self.lead.lead_id)
        self.service.send(queued.email_id)
        self.provider.send.assert_called_once()
        other_provider.send.assert_not_called()

    def test_authentication_api_approval_background_send_and_result_are_connected(self):
        app.dependency_overrides[get_email_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.pop, get_email_service, None)
        headers = {"Authorization": "Bearer " + "a" * 40}
        with patch("app.api.v1.calling_eligibility.get_settings", return_value=self.settings):
            with TestClient(app) as client:
                request = {"lead_id": self.lead.lead_id}
                for route in ["preview", "send"]:
                    self.assertEqual(client.post("/api/v1/emails/" + route, json=request).status_code, 401)
                    self.assertEqual(client.post("/api/v1/emails/" + route, json=request,
                                                 headers={"Authorization": "Bearer " + "r" * 40}).status_code, 401)
                self.assertEqual(client.put("/api/v1/emails/approval", json=request).status_code, 401)
                draft = client.post("/api/v1/emails/preview", json=request, headers=headers).json()
                self.assertNotIn("fixture-private-password", json.dumps(draft))
                rejected = client.post("/api/v1/emails/send", json=request, headers=headers)
                self.assertEqual(rejected.status_code, 403)
                failure_id = rejected.json()["detail"]["email_id"]
                self.assertEqual(client.get("/api/v1/emails/" + failure_id, headers=headers).json()["status"], "failed")
                approved = client.put("/api/v1/emails/approval", json=request | {
                    "review_id": draft["review_id"], "approved": True}, headers=headers)
                self.assertTrue(approved.json()["approved"])
                response = client.post("/api/v1/emails/send", json=request, headers=headers)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["status"], "pending")
                email_id = response.json()["email_id"]
                self.assertEqual(client.get("/api/v1/emails/" + email_id).status_code, 401)
                history = client.get("/api/v1/emails/" + email_id, headers=headers)
                self.assertEqual(history.json()["status"], "sent")
                self.assertEqual(history.json()["message_id"], "<fixture-msg-id@fixture.example>")
                self.assertNotIn("fixture-private-password", history.text)
                self.assertEqual(client.post("/api/v1/emails/send", json=request, headers=headers).json()["email_id"], email_id)
        self.provider.send.assert_called_once()

    def test_public_input_rejects_recipient_content_credentials_or_user_override(self):
        for extra in [{"recipient": "other@fixture.example"}, {"body": "Injected"}, {"smtp_password": "secret"}, {"user_id": "other"}]:
            with self.assertRaises(ValidationError):
                EmailRequest.model_validate({"lead_id": self.lead.lead_id} | extra)
        with self.assertRaises(ValidationError):
            EmailApprovalRequest(lead_id=self.lead.lead_id, review_id="0" * 64, approved="true")

    def test_storage_contains_no_sender_credentials_and_approval_survives_restart(self):
        self.approve()
        queued, _ = self.service.queue(self.lead.lead_id)
        self.service.send(queued.email_id)
        with closing(sqlite3.connect(self.settings.email_db_path)) as db:
            rows = db.execute("SELECT * FROM email_results").fetchall()
            approvals = db.execute("SELECT * FROM email_approvals").fetchall()
        serialized = json.dumps([rows, approvals])
        self.assertNotIn("fixture-private-password", serialized)
        self.assertNotIn("fixture-sender", serialized)
        self.assertTrue(EmailResultStore(self.settings.email_db_path).approved(queued.review_id))

    def test_default_is_disabled_and_password_is_redacted(self):
        settings = EmailSettings(_env_file=None)
        self.assertFalse(settings.email_sending_enabled)
        self.assertNotIn("fixture-private-password", repr(self.settings))
        self.assertEqual(Path(settings.email_db_path), Path.cwd() / "app/results/emails/emails.sqlite3")

    def test_invalid_smtp_configuration_does_not_change_voice_settings(self):
        with patch.dict(os.environ, {"SMTP_PORT": "invalid-port"}):
            self.assertFalse(Settings(_env_file=None).outbound_calls_enabled)
            with self.assertRaises(ValidationError):
                EmailSettings(_env_file=None)

    def test_result_lookup_missing_record_and_storage_failure_do_not_send(self):
        self.error(lambda: self.service.result(uuid4()), "email_not_found", 404)
        self.approve()
        with patch.object(self.service.store, "enqueue", side_effect=OSError("fixture disk failure")):
            with self.assertRaises(OSError):
                self.service.queue(self.lead.lead_id)
        self.provider.send.assert_not_called()

    def test_successful_send_populates_sent_at_and_message_id(self):
        self.approve()
        queued, _ = self.service.queue(self.lead.lead_id)
        self.service.send(queued.email_id)
        result = self.service.result(queued.email_id)
        self.assertEqual(result.status, "sent")
        self.assertIsNotNone(result.sent_at)
        self.assertEqual(result.message_id, "<fixture-msg-id@fixture.example>")

    def test_message_id_format_and_provider_return(self):
        draft = self.approve()
        from app.agents.email.agent import build_message
        message = build_message(draft)
        self.assertIn("Message-ID", message)
        msg_id = message["Message-ID"]
        self.assertTrue(msg_id.startswith("<") and msg_id.endswith(">"))
        self.assertIn("@", msg_id)

        with patch("app.integrations.smtp.smtplib.SMTP") as smtp:
            conn = smtp.return_value.__enter__.return_value
            conn.send_message.return_value = {}
            returned_id = SmtpEmailProvider(self.settings).send(message)
            self.assertEqual(returned_id, msg_id)

    def test_smtp_rejection_and_unexpected_exceptions_handling(self):
        # 1. SMTPResponseException (550) -> failed
        self.approve()
        self.provider.send.side_effect = smtplib.SMTPResponseException(550, b"User mailbox quota exceeded")
        queued, _ = self.service.queue(self.lead.lead_id)
        self.service.send(queued.email_id)
        res1 = self.service.result(queued.email_id)
        self.assertEqual(res1.status, "failed")
        self.assertIsNone(res1.sent_at)
        self.assertIsNone(res1.message_id)

        # 2. OSError / SMTPServerDisconnected -> uncertain
        self.proposal(proposed_service="Revision for OSError test")
        self.approve()
        self.provider.send.side_effect = OSError("Connection reset by peer")
        queued2, _ = self.service.queue(self.lead.lead_id)
        self.service.send(queued2.email_id)
        res2 = self.service.result(queued2.email_id)
        self.assertEqual(res2.status, "uncertain")
        self.assertIsNone(res2.sent_at)
        self.assertIsNone(res2.message_id)

        # 3. Unexpected exception (RuntimeError) -> uncertain
        self.proposal(proposed_service="Revision for unexpected exception test")
        self.approve()
        self.provider.send.side_effect = RuntimeError("Unexpected provider error")
        queued3, _ = self.service.queue(self.lead.lead_id)
        self.service.send(queued3.email_id)
        res3 = self.service.result(queued3.email_id)
        self.assertEqual(res3.status, "uncertain")
        self.assertIsNone(res3.sent_at)
        self.assertIsNone(res3.message_id)

    def test_retry_state_transitions_for_existing_review_records(self):
        # 1. New review -> pending + background send queued
        self.approve()
        first_result, first_should_send = self.service.queue(self.lead.lead_id)
        self.assertTrue(first_should_send)
        self.assertEqual(first_result.status, "pending")
        original_email_id = first_result.email_id

        # 2. Existing pending -> no duplicate retry
        pending_result, pending_should_send = self.service.queue(self.lead.lead_id)
        self.assertFalse(pending_should_send)
        self.assertEqual(pending_result.email_id, original_email_id)
        self.assertEqual(pending_result.status, "pending")

        # 3. Existing sending -> no duplicate retry
        claimed = self.service.store.claim(original_email_id)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, "sending")
        sending_result, sending_should_send = self.service.queue(self.lead.lead_id)
        self.assertFalse(sending_should_send)
        self.assertEqual(sending_result.email_id, original_email_id)
        self.assertEqual(sending_result.status, "sending")

        # 4. Existing uncertain -> retry queued
        self.service.store.finish(original_email_id, "uncertain", "email_provider_outcome_uncertain")
        unc_result = self.service.result(original_email_id)
        self.assertEqual(unc_result.status, "uncertain")

        retry_unc_result, retry_unc_should_send = self.service.queue(self.lead.lead_id)
        self.assertTrue(retry_unc_should_send)
        self.assertEqual(retry_unc_result.email_id, original_email_id)
        self.assertEqual(retry_unc_result.status, "pending")

        # 5. Existing failed -> retry queued
        self.service.store.claim(original_email_id)
        self.service.store.finish(original_email_id, "failed", "email_provider_rejected")
        fail_result = self.service.result(original_email_id)
        self.assertEqual(fail_result.status, "failed")

        retry_fail_result, retry_fail_should_send = self.service.queue(self.lead.lead_id)
        self.assertTrue(retry_fail_should_send)
        self.assertEqual(retry_fail_result.email_id, original_email_id)
        self.assertEqual(retry_fail_result.status, "pending")

        # 6. Existing sent -> no retry
        self.service.store.claim(original_email_id)
        self.service.store.finish(original_email_id, "sent", message_id="<msg-test@example.com>")
        sent_result = self.service.result(original_email_id)
        self.assertEqual(sent_result.status, "sent")

        retry_sent_result, retry_sent_should_send = self.service.queue(self.lead.lead_id)
        self.assertFalse(retry_sent_should_send)
        self.assertEqual(retry_sent_result.email_id, original_email_id)
        self.assertEqual(retry_sent_result.status, "sent")

        # 7. Check DB row count: verify no duplicate email_result rows created for review_id
        with closing(sqlite3.connect(self.settings.email_db_path)) as db:
            rows = db.execute("SELECT * FROM email_results WHERE review_id=?", (first_result.review_id,)).fetchall()
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
