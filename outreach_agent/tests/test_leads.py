import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models.leads import (
    LeadFileError,
    LeadOutcome,
    SourceLead,
    normalize_indian_mobile,
    prepare_lead,
)
from app.services.leads import LeadJsonService

client = TestClient(app)


def record(**changes):
    base = {
        "lead_id": "keep-this-id",
        "business": {
            "business_name": "Example Co",
            "website": None,
            "category": None,
            "address": None,
            "phone": "9876543210",
            "email": None,
        },
        "contacts": {"emails": [], "phone_numbers": []},
        "lead_scoring": {"lead_score": 42.5, "qualification_status": "Qualified"},
    }
    base.update(changes)
    return base


def test_normalizes_local_and_country_code_phone():
    assert normalize_indian_mobile("9876543210") == "+919876543210"
    assert normalize_indian_mobile("+919876543210") == "+919876543210"
    assert normalize_indian_mobile("91 98765 43210") == "+919876543210"


def test_rejects_eight_digit_number():
    with pytest.raises(ValueError):
        normalize_indian_mobile("41101424")


def test_preserves_id_deduplicates_and_tracks_original_phone():
    source = record(contacts={"emails": [], "phone_numbers": ["+919876543210", "41101424"]})
    lead = prepare_lead(SourceLead.model_validate(source))
    assert lead.lead_id == "keep-this-id"
    assert len(lead.phone_numbers) == 1
    assert lead.phone_numbers[0].normalized_value == "+919876543210"
    assert lead.phone_numbers[0].original_value == "9876543210"
    assert lead.invalid_phone_numbers[0].original_value == "41101424"
    assert lead.eligibility.outcome == LeadOutcome.manual_review
    assert not lead.eligibility.call_eligible


def test_missing_and_null_business_values_are_safe_and_no_phone_rejected():
    source = record(
        business={
            "business_name": None,
            "website": None,
            "category": None,
            "address": None,
            "phone": None,
            "email": None,
        },
        contacts={"emails": None, "phone_numbers": None},
    )
    lead = prepare_lead(SourceLead.model_validate(source))
    assert lead.business_name is None
    assert lead.phone_numbers == []
    assert lead.eligibility.outcome == LeadOutcome.rejected


def test_multiple_distinct_valid_phones_are_retained():
    source = record(contacts={"emails": [], "phone_numbers": ["+919876543210", "9123456789"]})
    lead = prepare_lead(SourceLead.model_validate(source))
    assert [phone.normalized_value for phone in lead.phone_numbers] == [
        "+919876543210",
        "+919123456789",
    ]


def test_needs_review_is_manual_review_even_with_valid_phone():
    source = record(lead_scoring={"lead_score": 53.1, "qualification_status": "Needs Review"})
    lead = prepare_lead(SourceLead.model_validate(source))
    assert lead.eligibility.outcome == LeadOutcome.manual_review
    assert not lead.eligibility.call_eligible


def test_consent_and_suppression_are_unapproved_by_default():
    lead = prepare_lead(SourceLead.model_validate(record()))
    gate = lead.eligibility.consent_suppression
    assert not gate.approved
    assert not gate.consent_or_lawful_basis_verified
    assert not gate.suppression_checked
    assert not gate.dispatch_enabled


def test_json_loader_success_missing_and_malformed(tmp_path: Path):
    data = tmp_path / "leads.json"
    data.write_text(json.dumps([record()]), encoding="utf-8")
    assert len(LeadJsonService(data).load()) == 1
    with pytest.raises(LeadFileError):
        LeadJsonService(tmp_path / "missing.json").load()
    data.write_text("{broken", encoding="utf-8")
    with pytest.raises(LeadFileError):
        LeadJsonService(data).load()


def test_preview_endpoint_uses_configured_temp_file(monkeypatch, tmp_path: Path):
    data = tmp_path / "leads.json"
    data.write_text(json.dumps([record()]), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "lead_json_path", str(data))
    reviewer_token = "test-reviewer-token-with-at-least-32-characters"
    monkeypatch.setattr(get_settings(), "eligibility_reviewer_token", reviewer_token)
    response = client.get("/api/v1/leads/preview",
                          headers={"Authorization": f"Bearer {reviewer_token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["eligible"] == 1
    assert payload["dispatch_enabled"] is False
    assert payload["leads"][0]["lead_id"] == "keep-this-id"
    assert not payload["leads"][0]["eligibility"]["consent_suppression"]["approved"]
