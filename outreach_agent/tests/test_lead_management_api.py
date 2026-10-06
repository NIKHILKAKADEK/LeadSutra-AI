import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import calls as calls_api
from app.core.config import get_settings
from app.main import app
from app.models.calling_eligibility import CheckStatus, ConsentRecordInput, SuppressionInput
from app.services.calling_eligibility import CallingEligibilityStore

client = TestClient(app)
REVIEWER_TOKEN = "module-3e-reviewer-token-with-enough-length-0001"
ADMIN_TOKEN = "module-3e-admin-token-with-enough-length-0000001"
PURPOSE = "commercial_sales_call"


def sample(lead_id="lead-1", name="Alpha Coffee", category="Cafe", qualification="Qualified",
           phone="9876543210"):
    return {
        "lead_id": lead_id,
        "business": {
            "business_name": name,
            "website": "https://example.invalid",
            "category": category,
            "address": "Example City",
            "phone": phone,
            "email": "private@example.invalid",
        },
        "contacts": {"emails": ["contact@example.invalid"], "phone_numbers": []},
        "lead_scoring": {"lead_score": 73.0, "qualification_status": qualification},
    }


def use_lead_file(monkeypatch, tmp_path: Path, records):
    path = tmp_path / "leads.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "lead_json_path", str(path))
    return path


def reviewer_headers():
    return {"Authorization": f"Bearer {REVIEWER_TOKEN}"}


def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def configure_tokens(monkeypatch):
    monkeypatch.setattr(get_settings(), "eligibility_reviewer_token", REVIEWER_TOKEN)
    monkeypatch.setattr(get_settings(), "eligibility_admin_token", ADMIN_TOKEN)


def test_list_leads_and_pagination(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [
        sample("lead-1", "Alpha Coffee"),
        sample("lead-2", "Beta Books", "Books", "Needs Review", "9123456789"),
        sample("lead-3", "Gamma Cafe", "Cafe", "Qualified", "9987654321"),
    ])
    response = client.get("/api/v1/leads", params={"limit": 1, "offset": 1}, headers=reviewer_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert [item["lead_id"] for item in payload["leads"]] == ["lead-2"]
    assert payload["leads"][0]["phone_numbers"] == ["+919123456789"]
    assert "email" not in payload["leads"][0]


def test_list_search_and_filters(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [
        sample("lead-1", "Alpha Coffee", "Cafe", "Qualified"),
        sample("lead-2", "Beta Books", "Books", "Needs Review", "9123456789"),
        sample("lead-3", "Gamma Cafe", "Cafe", "Qualified", "9987654321"),
    ])
    search = client.get("/api/v1/leads", params={"search": "coffee"}, headers=reviewer_headers())
    assert search.status_code == 200
    assert [item["lead_id"] for item in search.json()["leads"]] == ["lead-1"]

    filtered = client.get("/api/v1/leads", params={"qualification_status": "qualified", "category": "cafe"},
                          headers=reviewer_headers())
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert {item["lead_id"] for item in filtered.json()["leads"]} == {"lead-1", "lead-3"}


def test_lead_detail_and_unknown_id(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [sample()])
    response = client.get("/api/v1/leads/lead-1", headers=reviewer_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["business_name"] == "Alpha Coffee"
    assert body["phone_numbers"] == ["+919876543210"]
    assert body["qualification_status"] == "Qualified"
    assert body["contact_names"] == []
    assert "email_addresses" not in body
    assert "consent" not in body

    unknown = client.get("/api/v1/leads/no-such-lead", headers=reviewer_headers())
    assert unknown.status_code == 404


@pytest.mark.parametrize("contents", [None, "{malformed"])
def test_missing_or_malformed_lead_source_returns_safe_503(monkeypatch, tmp_path, contents):
    configure_tokens(monkeypatch)
    if contents is None:
        path = tmp_path / "missing.json"
    else:
        path = tmp_path / "malformed.json"
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(get_settings(), "lead_json_path", str(path))
    response = client.get("/api/v1/leads", headers=reviewer_headers())
    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "Lead source is unavailable."


def test_lead_reads_and_dispatch_reject_unauthenticated_requests(monkeypatch):
    configure_tokens(monkeypatch)
    response = client.get("/api/v1/leads")
    assert response.status_code == 401
    response = client.post("/api/v1/calls/dispatch", json={
        "lead_id": "lead-1", "phone_number": "+919876543210",
        "idempotency_key": "9e3cad9f-e623-4b2c-8fc9-ceaa71ef9e01",
    })
    assert response.status_code == 401


def test_selected_lead_eligibility_uses_backend_purpose_and_existing_evaluator(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [sample()])
    monkeypatch.setattr(get_settings(), "eligibility_db_path", str(tmp_path / "eligibility.sqlite3"))
    monkeypatch.setattr(get_settings(), "outbound_call_purpose", PURPOSE)
    response = client.get("/api/v1/calling-eligibility/lead-1",
                          params={"phone_number": "+919876543210", "purpose": "frontend-injected-purpose"},
                          headers=reviewer_headers())
    assert response.status_code == 200
    assert response.json()["eligible"] is False
    assert "consent_unknown" in response.json()["reason_codes"]


def seed_dispatch_eligibility(path: Path):
    store = CallingEligibilityStore(path)
    now = datetime.now(timezone.utc)
    store.save_consent(ConsentRecordInput(
        lead_id="lead-1", phone_number="+919876543210", consent_status="verified",
        consent_scope=PURPOSE, consent_source="fixture", evidence_reference="fixture:consent",
        verified_at=now, verified_by="fixture-reviewer",
    ))
    store.save_suppression(SuppressionInput(phone_number="+919876543210", suppression_status="not_suppressed"))
    store.save_telecom_checks("lead-1", "+919876543210", CheckStatus.approved,
                              CheckStatus.approved, "fixture:telecom")
    store.save_operational_check("lead-1", "+919876543210", CheckStatus.approved, 0, 3)


def test_valid_dispatch_request_is_dry_run_and_never_contacts_provider(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [sample()])
    db_path = tmp_path / "eligibility.sqlite3"
    seed_dispatch_eligibility(db_path)
    monkeypatch.setattr(get_settings(), "eligibility_db_path", str(db_path))
    monkeypatch.setattr(get_settings(), "outbound_calls_enabled", False)
    monkeypatch.setattr(get_settings(), "omnidim_outbound_agent_id", 261506)
    provider = Mock(side_effect=AssertionError("provider must not be constructed in dry-run mode"))
    monkeypatch.setattr(calls_api, "OmniDimensionDispatchProvider", provider)

    response = client.post("/api/v1/calls/dispatch", headers=admin_headers(), json={
        "lead_id": "lead-1", "phone_number": "+919876543210",
        "idempotency_key": "9e3cad9f-e623-4b2c-8fc9-ceaa71ef9e01",
    })
    assert response.status_code == 200
    assert response.json()["status"] == "dry_run"
    assert response.json()["eligible"] is True
    assert response.json()["dispatch_enabled"] is False
    assert response.json()["dispatched"] is False
    provider.assert_not_called()


def test_dispatch_rejects_phone_not_associated_with_lead(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [sample()])
    monkeypatch.setattr(get_settings(), "eligibility_db_path", str(tmp_path / "eligibility.sqlite3"))
    monkeypatch.setattr(get_settings(), "outbound_calls_enabled", False)
    monkeypatch.setattr(get_settings(), "omnidim_outbound_agent_id", 261506)
    response = client.post("/api/v1/calls/dispatch", headers=admin_headers(), json={
        "lead_id": "lead-1", "phone_number": "+919123456789",
        "idempotency_key": "9e3cad9f-e623-4b2c-8fc9-ceaa71ef9e01",
    })
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert "phone_not_associated_with_lead" in response.json()["reason_codes"]


def test_authenticated_dispatch_route_runs_with_isolated_fixtures_and_mock_provider(monkeypatch, tmp_path):
    configure_tokens(monkeypatch)
    use_lead_file(monkeypatch, tmp_path, [sample()])
    db_path = tmp_path / "eligibility.sqlite3"
    seed_dispatch_eligibility(db_path)
    settings = get_settings()
    monkeypatch.setattr(settings, "eligibility_db_path", str(db_path))
    # This is an in-memory test override only. The .env file and app default remain false.
    monkeypatch.setattr(settings, "outbound_calls_enabled", True)
    monkeypatch.setattr(settings, "outbound_call_purpose", PURPOSE)
    monkeypatch.setattr(settings, "omnidim_outbound_agent_id", 261506)
    monkeypatch.setattr(settings, "omnidim_api_key", "test-only-not-a-provider-credential")
    monkeypatch.setattr(settings, "outbound_represented_business_name", "Verified Caller Ltd.")

    provider = Mock()
    provider.get_agent.return_value = {
        "status": 200,
        "json": {"id": 261506, "bot_call_type": "Outgoing", "languages": [
            {"label": "English (India)"}, {"label": "Hindi"}, {"label": "Marathi"},
        ]},
    }
    provider.dispatch_call.return_value = {
        "status": 200,
        "json": {"success": True, "status": "dispatched", "requestId": "mock-route-1"},
    }
    provider_factory = Mock(return_value=provider)
    monkeypatch.setattr(calls_api, "OmniDimensionDispatchProvider", provider_factory)

    payload = {
        "lead_id": "lead-1",
        "phone_number": "+919876543210",
        "idempotency_key": "e16ea9ee-6ca8-4cb0-9858-42a30523c125",
    }
    invalid_request = client.post(
        "/api/v1/calls/dispatch",
        headers=admin_headers(),
        json={**payload, "agent_id": 999, "call_context": {"verified_business_name": "spoofed"}},
    )
    assert invalid_request.status_code == 422
    provider_factory.assert_not_called()

    unrelated_phone = client.post(
        "/api/v1/calls/dispatch",
        headers=admin_headers(),
        json={**payload, "phone_number": "+919123456789"},
    )
    assert unrelated_phone.status_code == 200
    assert unrelated_phone.json()["status"] == "blocked"
    assert "phone_not_associated_with_lead" in unrelated_phone.json()["reason_codes"]
    provider_factory.assert_not_called()

    monkeypatch.setattr(settings, "outbound_represented_business_identity_verified", False)
    unverified_identity = client.post(
        "/api/v1/calls/dispatch", headers=admin_headers(), json=payload,
    )
    assert unverified_identity.status_code == 200
    assert unverified_identity.json()["status"] == "blocked"
    assert "represented_business_identity_unverified" in unverified_identity.json()["reason_codes"]
    provider_factory.assert_not_called()

    monkeypatch.setattr(settings, "outbound_represented_business_identity_verified", True)
    eligible_dispatch = client.post(
        "/api/v1/calls/dispatch", headers=admin_headers(), json=payload,
    )
    assert eligible_dispatch.status_code == 200
    assert eligible_dispatch.json()["status"] == "dispatched"
    assert eligible_dispatch.json()["eligible"] is True
    assert eligible_dispatch.json()["dispatch_enabled"] is True
    provider_factory.assert_called_once_with("test-only-not-a-provider-credential")
    provider.get_agent.assert_called_once_with(261506)
    assert provider.dispatch_call.call_args.kwargs == {
        "agent_id": 261506,
        "to_number": "+919876543210",
        "call_context": {
            "lead_business_name": "Alpha Coffee",
            "verified_business_name": "Verified Caller Ltd.",
            "contact_basis_status": "verified",
        },
    }
