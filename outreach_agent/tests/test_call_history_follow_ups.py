import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models.call_dispatch import DispatchStatus
from app.services.call_dispatch import DispatchLedger

client = TestClient(app)
TOKEN = "module-3g-reviewer-token-with-enough-length-0001"
LEAD_ID = "history-lead"
CALL_A = UUID("44ce70b1-f34b-4a85-91d2-41e341ac12c5")
CALL_B = UUID("e7dfc0d0-91a5-4f07-b1c5-e7d711a8db33")


def lead(lead_id=LEAD_ID):
    return {"lead_id": lead_id,
            "business": {"business_name": "Fixture", "phone": "9876543210", "category": "Cafe"},
            "lead_scoring": {"qualification_status": "Qualified"}}


@pytest.fixture
def configured(monkeypatch, tmp_path):
    token = TOKEN
    monkeypatch.setattr(get_settings(), "eligibility_reviewer_token", token)
    monkeypatch.setattr(get_settings(), "eligibility_admin_token", "module-3g-admin-token-with-enough-length-0001")
    lead_path = tmp_path / "leads.json"
    lead_path.write_text(json.dumps([lead()]), encoding="utf-8")
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setattr(get_settings(), "lead_json_path", str(lead_path))
    monkeypatch.setattr(get_settings(), "eligibility_db_path", str(db_path))
    headers = {"Authorization": f"Bearer {token}"}
    ledger = DispatchLedger(db_path)
    ledger.claim(CALL_A, LEAD_ID, "+919876543210")
    ledger.finish(CALL_A, DispatchStatus.dispatched, "provider-request-1")
    ledger.claim(CALL_B, LEAD_ID, "+919876543210")
    ledger.finish(CALL_B, DispatchStatus.uncertain)
    return db_path, headers


def test_call_history_pagination_and_dispatch_outcome_distinction(configured):
    _, headers = configured
    response = client.get("/api/v1/calls", params={"limit": 1, "offset": 0}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["calls"]) == 1
    accepted = client.get(f"/api/v1/calls/{CALL_A}", headers=headers).json()
    assert accepted["dispatch_status"] == "dispatched"
    assert accepted["dispatch_requested"] is True
    assert accepted["provider_accepted"] is True
    assert accepted["call_outcome"] == "unknown"
    assert "transcript" not in accepted
    uncertain = client.get(f"/api/v1/calls/{CALL_B}", headers=headers).json()
    assert uncertain["provider_accepted"] is False
    assert uncertain["call_outcome"] == "unknown"


def test_lead_call_history_and_unknown_call(configured):
    _, headers = configured
    response = client.get(f"/api/v1/leads/{LEAD_ID}/calls", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert client.get("/api/v1/calls/11111111-1111-4111-8111-111111111111", headers=headers).status_code == 404


def test_follow_up_create_related_call_validation_and_idempotency(configured):
    _, headers = configured
    payload = {"lead_id": LEAD_ID, "related_call_id": str(CALL_A),
               "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
               "notes": "review callback", "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda231"}
    created = client.post("/api/v1/follow-ups", headers=headers, json=payload)
    assert created.status_code == 201
    record = created.json()
    assert record["status"] == "pending"
    assert record["related_call_id"] == str(CALL_A)
    assert record["assigned_reviewer"] is None
    assert client.get(f"/api/v1/follow-ups/{record['follow_up_id']}", headers=headers).json() == record
    retried = client.post("/api/v1/follow-ups", headers=headers, json=payload)
    assert retried.status_code == 201
    assert retried.json()["follow_up_id"] == record["follow_up_id"]
    assert client.get("/api/v1/follow-ups", headers=headers).json()["total"] == 1
    reused_key = {**payload, "notes": "different payload"}
    assert client.post("/api/v1/follow-ups", headers=headers, json=reused_key).status_code == 409

    wrong_call = {**payload, "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda232",
                  "related_call_id": "99999999-9999-4999-8999-999999999999"}
    assert client.post("/api/v1/follow-ups", headers=headers, json=wrong_call).status_code == 422
    other_lead_call = UUID("9bdf839f-42fc-40b7-ae71-d5fed90497ef")
    ledger = DispatchLedger(configured[0])
    ledger.claim(other_lead_call, "other-lead", "+919876543210")
    ledger.finish(other_lead_call, DispatchStatus.dispatched)
    mismatched_call = {**payload, "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda237",
                       "related_call_id": str(other_lead_call)}
    assert client.post("/api/v1/follow-ups", headers=headers, json=mismatched_call).status_code == 422
    bad_lead = {**payload, "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda233",
                "lead_id": "missing"}
    assert client.post("/api/v1/follow-ups", headers=headers, json=bad_lead).status_code == 404


def test_follow_up_update_terminal_transitions_and_timezone(configured):
    _, headers = configured
    payload = {"lead_id": LEAD_ID,
               "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
               "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda234"}
    created = client.post("/api/v1/follow-ups", headers=headers, json=payload).json()
    follow_id = created["follow_up_id"]
    updated = client.patch(f"/api/v1/follow-ups/{follow_id}", headers=headers,
                          json={"notes": "updated"})
    assert updated.status_code == 200
    assert updated.json()["notes"] == "updated"
    completed = client.patch(f"/api/v1/follow-ups/{follow_id}", headers=headers,
                             json={"status": "completed"})
    assert completed.json()["status"] == "completed"
    assert client.patch(f"/api/v1/follow-ups/{follow_id}", headers=headers,
                        json={"status": "pending"}).status_code == 409
    assert client.patch(f"/api/v1/follow-ups/{follow_id}", headers=headers,
                        json={"scheduled_at": datetime.now(timezone.utc).isoformat()}).status_code == 409

    naive = {**payload, "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda235",
             "scheduled_at": "2030-01-01T09:00:00"}
    assert client.post("/api/v1/follow-ups", headers=headers, json=naive).status_code == 422


def test_follow_up_cancel_and_authentication(configured):
    _, headers = configured
    payload = {"lead_id": LEAD_ID, "scheduled_at": "2030-01-01T09:00:00+05:30",
               "idempotency_key": "b93a789e-26db-4322-8a29-101c6ffda236"}
    created = client.post("/api/v1/follow-ups", headers=headers, json=payload).json()
    cancelled = client.patch(f"/api/v1/follow-ups/{created['follow_up_id']}", headers=headers,
                             json={"status": "cancelled"})
    assert cancelled.json()["status"] == "cancelled"
    assert client.patch(f"/api/v1/follow-ups/{created['follow_up_id']}", headers=headers,
                        json={"status": "pending"}).status_code == 409
    assert client.get("/api/v1/calls").status_code == 401
    assert client.get("/api/v1/follow-ups").status_code == 401
