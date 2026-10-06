from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock
from uuid import UUID

import pytest
from omnidimension import APIError
from pydantic import ValidationError

from app.core.config import Settings
from app.models.call_dispatch import DispatchRequest, DispatchStatus
from app.models.calling_eligibility import (
    CheckStatus, ConsentRecordInput, SuppressionInput,
)
from app.models.leads import SourceLead, prepare_lead
from app.services.call_dispatch import CallDispatchService, DispatchLedger
from app.services.calling_eligibility import CallingEligibilityStore
from app.services.voice_agent_configs import outbound_agent_config

LEAD_ID = "dispatch-fixture"
PHONE = "+919876543210"
PURPOSE = "commercial_sales_call"
AGENT_ID = 261506
KEY = UUID("b05b66a7-51ab-4387-bfb4-3a94662f790d")


class FixtureLeads:
    def __init__(self, *, optional_fields=True):
        business = {"business_name": "Fixture Business", "phone": "9876543210"}
        if optional_fields:
            business.update({"website": "https://example.invalid", "category": "Retail",
                             "address": "Fixture City", "email": "private@example.invalid"})
        self._leads = [prepare_lead(SourceLead.model_validate({
            "lead_id": LEAD_ID,
            "business": business,
            "lead_scoring": {"qualification_status": "Qualified"},
        }))]

    def load(self):
        return self._leads


@pytest.fixture
def setup_dispatch(tmp_path):
    store = CallingEligibilityStore(tmp_path / "eligibility.sqlite3")
    now = datetime.now(timezone.utc)
    store.save_suppression(SuppressionInput(phone_number=PHONE, suppression_status="not_suppressed"))
    store.save_telecom_checks(LEAD_ID, PHONE, CheckStatus.approved, CheckStatus.approved, "fixture:telecom")
    store.save_operational_check(LEAD_ID, PHONE, CheckStatus.approved, 0, 3)
    store.save_consent(ConsentRecordInput(
        lead_id=LEAD_ID, phone_number=PHONE, consent_status="verified",
        consent_scope=PURPOSE, consent_source="test fixture", evidence_reference="fixture:consent",
        verified_at=now, verified_by="test-reviewer",
    ))
    provider = Mock()
    provider.get_agent.return_value = {
        "status": 200,
        "json": {"id": AGENT_ID, "bot_call_type": "Outgoing",
                 "languages": [{"label": "English (India)"}, {"label": "Hindi"}, {"label": "Marathi"}]},
    }
    provider.dispatch_call.return_value = {
        "status": 200,
        "json": {"success": True, "status": "dispatched", "requestId": 835014},
    }
    factory = Mock(return_value=provider)

    def service(*, agent_id=AGENT_ID, enabled=True, represented_business_name="Verified Caller Ltd.",
                identity_verified=True, optional_fields=True):
        return CallDispatchService(
            lead_service=FixtureLeads(optional_fields=optional_fields), eligibility_store=store,
            ledger=DispatchLedger(tmp_path / "eligibility.sqlite3"),
            provider_factory=factory, agent_id=agent_id, enabled=enabled, purpose=PURPOSE,
            represented_business_name=represented_business_name,
            represented_business_identity_verified=identity_verified,
        )

    return store, provider, factory, service


def test_eligible_lead_dispatches_and_sends_minimal_context(setup_dispatch):
    _, provider, _, service = setup_dispatch
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.dispatched
    assert result.dispatched is True
    assert result.provider_request_id == "835014"
    args = provider.dispatch_call.call_args.kwargs
    assert args["agent_id"] == AGENT_ID
    assert args["to_number"] == PHONE
    assert args["call_context"] == {
        "lead_business_name": "Fixture Business",
        "verified_business_name": "Verified Caller Ltd.",
        "contact_basis_status": "verified",
    }
    agent_config = outbound_agent_config()
    assert set(args["call_context"]).issubset(agent_config["dynamic_variables"])
    assert agent_config["languages"] == ["English (India)", "Hindi", "Marathi"]


def test_unknown_consent_blocks_without_provider_call(setup_dispatch):
    store, provider, factory, service = setup_dispatch
    with store._connect() as db:
        db.execute("DELETE FROM consent_records WHERE lead_id=?", (LEAD_ID,))
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.blocked
    assert "consent_unknown" in result.reason_codes
    factory.assert_not_called()
    provider.dispatch_call.assert_not_called()


def test_revoked_consent_blocks_dispatch(setup_dispatch):
    store, provider, _, service = setup_dispatch
    now = datetime.now(timezone.utc)
    store.save_consent(ConsentRecordInput(
        lead_id=LEAD_ID, phone_number=PHONE, consent_status="revoked",
        revoked_at=now,
    ))
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.blocked
    assert "consent_revoked" in result.reason_codes
    provider.dispatch_call.assert_not_called()


def test_suppressed_phone_blocks_dispatch(setup_dispatch):
    store, provider, _, service = setup_dispatch
    store.save_suppression(SuppressionInput(phone_number=PHONE, suppression_status="suppressed"))
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.blocked
    assert "phone_suppressed" in result.reason_codes
    provider.dispatch_call.assert_not_called()


def test_unknown_telecom_check_blocks_dispatch(setup_dispatch):
    store, provider, _, service = setup_dispatch
    with store._connect() as db:
        db.execute("DELETE FROM telecom_checks WHERE lead_id=?", (LEAD_ID,))
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.blocked
    assert "telecom_preference_unverified" in result.reason_codes
    provider.dispatch_call.assert_not_called()


def test_invalid_phone_blocks_dispatch(setup_dispatch):
    _, provider, factory, service = setup_dispatch
    result = service().run(LEAD_ID, "12345", KEY)
    assert result.status == DispatchStatus.blocked
    assert result.reason_codes == ["phone_invalid"]
    factory.assert_not_called()
    provider.dispatch_call.assert_not_called()


def test_missing_agent_id_blocks_dispatch(setup_dispatch):
    _, provider, factory, service = setup_dispatch
    result = service(agent_id=None).run(LEAD_ID, PHONE, KEY)
    assert result.reason_codes == ["outbound_agent_not_configured"]
    factory.assert_not_called()
    provider.dispatch_call.assert_not_called()


def test_agent_not_configured_as_outbound_blocks_dispatch(setup_dispatch):
    _, provider, _, service = setup_dispatch
    provider.get_agent.return_value = {
        "status": 200,
        "json": {"id": AGENT_ID, "bot_call_type": "Incoming",
                 "languages": [{"label": "English (India)"}, {"label": "Hindi"}, {"label": "Marathi"}]},
    }
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.blocked
    assert result.reason_codes == ["configured_agent_is_not_outbound"]
    provider.dispatch_call.assert_not_called()


def test_agent_missing_approved_languages_blocks_dispatch(setup_dispatch):
    _, provider, _, service = setup_dispatch
    provider.get_agent.return_value = {
        "status": 200,
        "json": {"id": AGENT_ID, "bot_call_type": "Outgoing", "languages": [{"label": "English (India)"}]},
    }
    result = service().run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.blocked
    assert result.reason_codes == ["agent_languages_unverified"]
    provider.dispatch_call.assert_not_called()


def test_provider_error_is_sanitized_and_not_retried(setup_dispatch):
    _, provider, _, service = setup_dispatch
    provider.dispatch_call.side_effect = APIError(503, "sensitive provider response")
    dispatcher = service()
    result = dispatcher.run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.provider_error
    assert "sensitive provider response" not in str(result.model_dump())
    retry = dispatcher.run(LEAD_ID, PHONE, KEY)
    assert retry.status == DispatchStatus.duplicate
    provider.dispatch_call.assert_called_once()


def test_uncertain_provider_response_is_not_retried(setup_dispatch):
    _, provider, _, service = setup_dispatch
    provider.dispatch_call.side_effect = APIError(0, "timeout")
    dispatcher = service()
    result = dispatcher.run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.uncertain
    retry = dispatcher.run(LEAD_ID, PHONE, KEY)
    assert retry.status == DispatchStatus.duplicate
    assert retry.reason_codes == ["previous_dispatch_outcome_uncertain"]
    provider.dispatch_call.assert_called_once()


def test_duplicate_idempotency_key_dispatches_once(setup_dispatch):
    _, provider, _, service = setup_dispatch
    dispatcher = service()
    assert dispatcher.run(LEAD_ID, PHONE, KEY).status == DispatchStatus.dispatched
    duplicate = dispatcher.run(LEAD_ID, PHONE, KEY)
    assert duplicate.status == DispatchStatus.duplicate
    provider.dispatch_call.assert_called_once()


def test_disabled_dispatch_is_dry_run_and_never_contacts_provider(setup_dispatch):
    _, provider, factory, service = setup_dispatch
    result = service(enabled=False).run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.dry_run
    assert result.eligible is True
    assert result.dispatched is False
    factory.assert_not_called()
    provider.dispatch_call.assert_not_called()


def test_missing_or_unverified_represented_business_blocks_enabled_dispatch(setup_dispatch):
    _, provider, factory, service = setup_dispatch
    missing = service(represented_business_name=None).run(LEAD_ID, PHONE, KEY)
    assert missing.status == DispatchStatus.blocked
    assert "represented_business_identity_unverified" in missing.reason_codes
    unverified = service(identity_verified=False).run(LEAD_ID, PHONE, KEY)
    assert unverified.status == DispatchStatus.blocked
    assert "represented_business_identity_unverified" in unverified.reason_codes
    factory.assert_not_called()
    provider.dispatch_call.assert_not_called()


def test_missing_optional_lead_fields_are_omitted_from_call_context(setup_dispatch):
    _, provider, _, service = setup_dispatch
    result = service(optional_fields=False).run(LEAD_ID, PHONE, KEY)
    assert result.status == DispatchStatus.dispatched
    context = provider.dispatch_call.call_args.kwargs["call_context"]
    assert context == {
        "lead_business_name": "Fixture Business",
        "verified_business_name": "Verified Caller Ltd.",
        "contact_basis_status": "verified",
    }
    assert "website" not in context
    assert "business_location" not in context


def test_dispatch_request_rejects_arbitrary_agent_id_and_context():
    with pytest.raises(ValidationError):
        DispatchRequest.model_validate({
            "lead_id": LEAD_ID,
            "phone_number": PHONE,
            "idempotency_key": str(KEY),
            "agent_id": 999,
            "call_context": {"verified_business_name": "attacker supplied"},
        })


def test_outbound_provider_dispatch_is_disabled_by_default():
    assert Settings.model_fields["outbound_calls_enabled"].default is False


def test_eligibility_change_after_agent_verification_blocks_before_dispatch(setup_dispatch):
    store, provider, _, service = setup_dispatch
    dispatcher = service()
    agent_response = provider.get_agent.return_value

    def revoke_consent_before_second_check(_agent_id):
        store.save_consent(ConsentRecordInput(
            lead_id=LEAD_ID,
            phone_number=PHONE,
            consent_status="revoked",
            revoked_at=datetime.now(timezone.utc),
        ))
        return agent_response

    provider.get_agent.side_effect = revoke_consent_before_second_check

    result = dispatcher.run(LEAD_ID, PHONE, KEY)

    assert result.status == DispatchStatus.blocked
    assert "consent_revoked" in result.reason_codes
    provider.get_agent.assert_called_once_with(AGENT_ID)
    provider.dispatch_call.assert_not_called()
    assert DispatchLedger(store.path).lookup(KEY)[2] == DispatchStatus.blocked.value


def test_generic_timeout_is_uncertain_and_same_key_is_not_retried(setup_dispatch):
    store, provider, _, service = setup_dispatch
    provider.dispatch_call.side_effect = TimeoutError("test-only simulated transport timeout")
    dispatcher = service()

    result = dispatcher.run(LEAD_ID, PHONE, KEY)

    assert result.status == DispatchStatus.uncertain
    assert result.reason_codes == ["provider_outcome_uncertain"]
    assert "test-only simulated transport timeout" not in str(result.model_dump())
    assert DispatchLedger(store.path).lookup(KEY)[2] == DispatchStatus.uncertain.value

    retry = dispatcher.run(LEAD_ID, PHONE, KEY)

    assert retry.status == DispatchStatus.duplicate
    assert retry.reason_codes == ["previous_dispatch_outcome_uncertain"]
    provider.dispatch_call.assert_called_once()


def test_concurrent_same_idempotency_key_dispatches_at_most_once(setup_dispatch):
    _, provider, _, service = setup_dispatch
    agent_reads = Barrier(2)
    agent_response = provider.get_agent.return_value

    def synchronize_agent_verification(_agent_id):
        agent_reads.wait(timeout=5)
        return agent_response

    provider.get_agent.side_effect = synchronize_agent_verification
    dispatcher = service()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(dispatcher.run, LEAD_ID, PHONE, KEY) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]

    statuses = sorted(result.status.value for result in results)
    assert statuses == sorted([DispatchStatus.dispatched.value, DispatchStatus.duplicate.value])
    assert sum(result.dispatched for result in results) == 1
    provider.dispatch_call.assert_called_once()
