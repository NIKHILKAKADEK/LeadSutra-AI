"""Test suite for FastAPI endpoints including search, workflows, approval, and UI."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.app import app
from app.agents.lead_pipeline.schemas import (
    DiscoveryData,
    EnrichmentData,
    LeadDiscoveryRunResult,
    LeadResult,
    ScoringData,
    WebsiteCrawlResult,
    WebsiteStatus,
)


@pytest.fixture
def client():
    return TestClient(app)


def fake_lead(lead_id: str = "lead_test_api_1") -> LeadResult:
    return LeadResult(
        lead_id=lead_id,
        discovery=DiscoveryData(
            business_name="Acme Technologies",
            category="Software House",
            address="Sharanpur Road, Nashik",
            phone="+919876543210",
            website="https://acmetech.com",
            rating=4.7,
            source_url="https://maps.google.com/?q=acme",
        ),
        enrichment=EnrichmentData(
            website_url="https://acmetech.com",
            website_status=WebsiteStatus.ACTIVE.value,
            about="Acme Technologies builds software.",
            services=["Mobile Apps", "Web Development"],
            emails=["info@acmetech.com"],
            phone_numbers=["+919876543210"],
        ),
        scoring=ScoringData(
            lead_score=85.0,
            priority="High",
            qualification_status="Qualified",
            score_breakdown={"website": 25, "phone": 20},
        ),
    )


def test_ui_and_health_endpoints(client):
    # Root HTML response
    resp = client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "LeadSutra" in resp.text

    # Explicit /ui
    resp_ui = client.get("/ui")
    assert resp_ui.status_code == 200
    assert "LeadSutra" in resp_ui.text

    # JSON root
    resp_json = client.get("/", headers={"accept": "application/json"})
    assert resp_json.status_code == 200
    assert resp_json.json()["status"] == "running"

    # Health
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "healthy"


def test_lead_search_endpoint(client):
    lead = fake_lead()
    mock_run = LeadDiscoveryRunResult(leads=[lead], source="google_places", fallback_used=False)

    with patch("app.graph.nodes.LeadPipeline.run", new_callable=AsyncMock, return_value=mock_run):
        resp = client.post("/api/leads/search", json={"query": "Software House in Nashik", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 1
        assert "workflow_id" in data
        assert data["leads"][0]["lead_id"] == "lead_test_api_1"


def test_lead_get_by_id_endpoint(client):
    lead = fake_lead("lead_test_specific")
    with patch("app.services.lead_results.LeadResultStore.get_by_id", return_value=lead):
        resp = client.get("/api/leads/lead_test_specific")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lead_id"] == "lead_test_specific"
        assert data["discovery"]["business_name"] == "Acme Technologies"

    # 404 for unknown lead
    with patch("app.services.lead_results.LeadResultStore.get_by_id", return_value=None):
        resp_404 = client.get("/api/leads/unknown_id")
        assert resp_404.status_code == 404


def test_workflow_lifecycle_api(client):
    lead = fake_lead("lead_wf_lifecycle")
    mock_run = LeadDiscoveryRunResult(leads=[lead], source="google_places", fallback_used=False)

    # 1. Start workflow
    with patch("app.graph.nodes.LeadPipeline.run", new_callable=AsyncMock, return_value=mock_run):
        start_resp = client.post("/api/v1/workflows", json={"query": "Dentists in Nashik", "limit": 2})
        assert start_resp.status_code == 200
        wf_id = start_resp.json()["workflow_id"]
        assert start_resp.json()["execution_status"] == "WAITING_FOR_USER_SELECTION"

    # 2. Get workflow state
    get_resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["workflow_id"] == wf_id

    # 3. Select lead
    mock_res = {
        "business_summary": "Top dental clinic in Nashik.",
        "products_services": ["Dentistry"],
        "target_audience": "Families",
        "pain_points": ["Not enough information to determine from provided data"],
        "swot": {"strengths": ["Clean environment"], "weaknesses": [], "opportunities": [], "threats": []},
        "ideal_customer_profile": "Local residents",
        "decision_maker_identification": "Doctor",
        "sales_opportunities": [],
        "provided_facts": ["Address is Nashik"],
        "reasonable_inferences": [],
        "missing_information": [],
    }
    mock_prop = {
        "business_summary": "Top dental clinic in Nashik.",
        "identified_needs": ["Not enough information to determine from provided data"],
        "proposed_solution": "Patient appointment automation",
        "deliverables": ["Online booking widget"],
        "implementation_timeline": ["2 weeks"],
        "expected_benefits": ["Lower no-shows"],
        "pricing_suggestion": "Not available from provided data",
        "next_steps": ["Call clinic manager"],
        "email_subject_options": ["Appointment scheduling for your clinic"],
        "personalized_email": "Hi Doctor, we help dental practices...",
    }

    mock_crawl = WebsiteCrawlResult(
        lead_id="lead_wf_lifecycle",
        website_status=WebsiteStatus.UNREACHABLE,
    )
    with patch("app.graph.nodes.research_agent", return_value=mock_res), \
         patch("app.graph.nodes.proposal_agent", return_value=mock_prop), \
         patch("app.integrations.website_fetcher.WebsiteCrawler.crawl", new_callable=AsyncMock, return_value=mock_crawl):
        sel_resp = client.post(f"/api/v1/workflows/{wf_id}/select", json={"lead_id": "lead_wf_lifecycle"})
        assert sel_resp.status_code == 200
        sel_data = sel_resp.json()
        assert sel_data["execution_status"] == "WAITING_FOR_USER_APPROVAL"
        assert sel_data["proposal"]["proposed_solution"] == "Patient appointment automation"

    # 4. Results endpoint
    results_resp = client.get(f"/api/v1/workflows/{wf_id}/results")
    assert results_resp.status_code == 200
    assert results_resp.json()["proposal"]["proposed_solution"] == "Patient appointment automation"

    # 5. Approve proposal
    appr_resp = client.post(f"/api/v1/workflows/{wf_id}/approve", json={"approved": True})
    assert appr_resp.status_code == 200
    assert appr_resp.json()["approval_status"] == "approved"

    # 6. Authorize outreach
    with patch("app.graph.nodes.get_email_settings") as mock_settings:
        mock_settings.return_value.email_sending_enabled = False
        outreach_resp = client.post(f"/api/v1/workflows/{wf_id}/outreach", json={"channel": "email", "confirm_approved": True})
        assert outreach_resp.status_code == 200
        assert outreach_resp.json()["execution_status"] == "COMPLETED"
        assert outreach_resp.json()["outreach_result"]["status"] == "dry_run"
