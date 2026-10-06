from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import calling_eligibility as api
from app.core.config import get_settings
from app.main import app
from app.models.calling_eligibility import (
    CheckStatus, ConsentRecordInput, ConsentStatus, SuppressionInput,
)
from app.models.leads import SourceLead, prepare_lead
from app.services.calling_eligibility import (
    CallingEligibilityStore, check_consent, evaluate_eligibility,
)

NOW = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
LEAD_ID = "fixture-lead"
PHONE = "+919876543210"
PURPOSE = "commercial_sales_call"


def lead():
    source = SourceLead.model_validate({
        "lead_id": LEAD_ID,
        "business": {"business_name": "Fixture Business", "phone": "9876543210"},
        "lead_scoring": {"qualification_status": "Qualified"},
    })
    return prepare_lead(source)


def store(tmp_path):
    result = CallingEligibilityStore(tmp_path / "eligibility.sqlite3")
    result.save_consent(ConsentRecordInput(
        lead_id=LEAD_ID, phone_number=PHONE, consent_status=ConsentStatus.verified,
        consent_scope=PURPOSE, consent_source="test fixture", evidence_reference="fixture:consent-1",
        recorded_at=NOW - timedelta(days=1), verified_at=NOW - timedelta(days=1),
        verified_by="fixture-reviewer", expiry_at=NOW + timedelta(days=1),
    ))
    result.save_suppression(SuppressionInput(phone_number=PHONE, suppression_status="not_suppressed"))
    result.save_telecom_checks(LEAD_ID, PHONE, CheckStatus.approved, CheckStatus.approved, "fixture:telecom-1")
    return result


def evaluate(db, *, phone=PHONE, purpose=PURPOSE, **kwargs):
    defaults = dict(lead_id=LEAD_ID, phone_number=phone, leads=[lead()], store=db,
                    purpose=purpose, telecom_preference=CheckStatus.approved,
                    calling_route=CheckStatus.approved, calling_hours=CheckStatus.approved,
                    attempts_used=0, attempt_limit=3, operational_checked_at=NOW.isoformat(), now=NOW)
    defaults.update(kwargs)
    return evaluate_eligibility(**defaults)


@pytest.mark.parametrize("status,reason", [
    (ConsentStatus.unknown, "consent_unknown"),
    (ConsentStatus.denied, "consent_denied"),
    (ConsentStatus.revoked, "consent_revoked"),
    (ConsentStatus.pending_verification, "consent_pending_verification"),
])
def test_non_verified_consent_blocks(tmp_path, status, reason):
    db = CallingEligibilityStore(tmp_path / "db.sqlite3")
    payload = dict(lead_id=LEAD_ID, phone_number=PHONE, consent_status=status)
    if status == ConsentStatus.revoked:
        payload["revoked_at"] = NOW
    db.save_consent(ConsentRecordInput(**payload))
    assert check_consent(db.get_consent(LEAD_ID, PHONE), PURPOSE, NOW) == (False, reason)
    assert not evaluate(db).eligible


def test_new_consent_defaults_to_unknown_and_verified_valid_passes(tmp_path):
    unknown = ConsentRecordInput(lead_id=LEAD_ID, phone_number=PHONE)
    assert unknown.consent_status == ConsentStatus.unknown
    db = store(tmp_path)
    assert check_consent(db.get_consent(LEAD_ID, PHONE), PURPOSE, NOW) == (True, None)


def test_expired_consent_blocks(tmp_path):
    db = CallingEligibilityStore(tmp_path / "db.sqlite3")
    db.save_consent(ConsentRecordInput(
        lead_id=LEAD_ID, phone_number=PHONE, consent_status="verified", consent_scope=PURPOSE,
        consent_source="fixture", evidence_reference="fixture:expired", verified_at=NOW-timedelta(days=3),
        verified_by="fixture", expiry_at=NOW,
    ))
    assert check_consent(db.get_consent(LEAD_ID, PHONE), PURPOSE, NOW) == (False, "consent_expired")


def test_missing_evidence_and_wrong_purpose_block():
    assert check_consent({"consent_status": "verified", "consent_scope": PURPOSE}, PURPOSE, NOW) == (
        False, "consent_evidence_missing")
    assert check_consent({"consent_status": "verified", "consent_scope": PURPOSE,
                          "consent_source": "fixture", "evidence_reference": "fixture:1",
                          "verified_at": NOW.isoformat(), "verified_by": "fixture", "revoked_at": None,
                          "expiry_at": None}, "another_purpose", NOW) == (False, "consent_purpose_mismatch")


def test_unknown_suppression_blocks(tmp_path):
    db = CallingEligibilityStore(tmp_path / "db.sqlite3")
    db.save_consent(ConsentRecordInput(
        lead_id=LEAD_ID, phone_number=PHONE, consent_status="verified", consent_scope=PURPOSE,
        consent_source="fixture", evidence_reference="fixture:1", verified_at=NOW,
        verified_by="fixture",
    ))
    result = evaluate(db)
    assert not result.eligible
    assert "suppression_unknown" in result.reason_codes


def test_suppression_overrides_verified_consent(tmp_path):
    db = store(tmp_path)
    db.save_suppression(SuppressionInput(phone_number=PHONE, suppression_status="suppressed"))
    assert "phone_suppressed" in evaluate(db).reason_codes
    assert not evaluate(db).eligible


def test_invalid_phone_blocks(tmp_path):
    result = evaluate(store(tmp_path), phone="12345")
    assert not result.eligible
    assert result.reason_codes == ["phone_invalid"]


def test_unapproved_telecom_and_operational_checks_block(tmp_path):
    db = store(tmp_path)
    result = evaluate(db, telecom_preference=CheckStatus.unknown, calling_route=CheckStatus.denied,
                      calling_hours=CheckStatus.unknown, attempts_used=None, attempt_limit=None)
    assert not result.eligible
    assert {"telecom_preference_unverified", "calling_route_unapproved",
            "calling_hours_unverified", "attempt_limit_unverified"}.issubset(result.reason_codes)


def test_fully_eligible_fixture_passes(tmp_path):
    result = evaluate(store(tmp_path))
    assert result.eligible
    assert result.reason_codes == []
    assert result.normalized_phone_number == PHONE


def test_suppression_and_consent_endpoints_require_admin_auth(monkeypatch, tmp_path):
    admin_token = "fixture-admin-token-with-sufficient-random-length-0001"
    monkeypatch.setattr(get_settings(), "eligibility_admin_token", admin_token)
    monkeypatch.setattr(get_settings(), "eligibility_reviewer_token", "fixture-review-token-with-sufficient-random-length-0002")
    monkeypatch.setattr(get_settings(), "eligibility_db_path", str(tmp_path / "api.sqlite3"))
    client = TestClient(app)
    assert client.put("/api/v1/calling-eligibility/suppression",
                      json={"phone_number": PHONE, "suppression_status": "suppressed"}).status_code == 401
    response = client.put("/api/v1/calling-eligibility/suppression",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"phone_number": PHONE, "suppression_status": "suppressed"})
    assert response.status_code == 200
    assert response.json()["suppression_status"] == "suppressed"
