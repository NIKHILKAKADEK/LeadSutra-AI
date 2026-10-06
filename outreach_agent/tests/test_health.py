"""Tests for application startup and base routes."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_application_imports_and_starts() -> None:
    assert app.title == "LeadSutra AI Backend"


def test_health_endpoint_response_structure() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application": "LeadSutra AI Backend",
        "environment": "development",
        "api_version": "v1",
    }


def test_versioned_router_is_registered() -> None:
    response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {"version": "v1", "status": "available"}
