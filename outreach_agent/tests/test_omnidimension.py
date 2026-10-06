"""Mocked endpoint tests for OmniDimension connectivity."""

from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import omnidimension

client = TestClient(app)
CONNECTION_URL = "/api/v1/integrations/omnidimension/connection"


def test_connection_check_succeeds_without_exposing_agent_data(
    monkeypatch,
) -> None:
    monkeypatch.setattr(get_settings(), "omnidim_api_key", "test-secret")
    agent_api = Mock()
    agent_api.list.return_value = {"agents": [{"id": "private-agent-data"}]}
    sdk_client = Mock(agent=agent_api)
    sdk_constructor = Mock(return_value=sdk_client)
    monkeypatch.setattr(omnidimension, "Client", sdk_constructor)

    response = client.get(CONNECTION_URL)

    assert response.status_code == 200
    assert response.json() == {
        "status": "connected",
        "provider": "omnidimension",
    }
    assert "test-secret" not in response.text
    assert "private-agent-data" not in response.text
    sdk_constructor.assert_called_once_with("test-secret")
    agent_api.list.assert_called_once_with()


def test_connection_check_reports_missing_api_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "omnidim_api_key", None)
    sdk_constructor = Mock()
    monkeypatch.setattr(omnidimension, "Client", sdk_constructor)

    response = client.get(CONNECTION_URL)

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "unavailable",
            "provider": "omnidimension",
            "message": "OmniDimension API key is not configured.",
        }
    }
    sdk_constructor.assert_not_called()


def test_connection_check_sanitizes_sdk_failure(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "omnidim_api_key", "test-secret")
    sdk_constructor = Mock(side_effect=RuntimeError("sensitive provider response"))
    monkeypatch.setattr(omnidimension, "Client", sdk_constructor)

    response = client.get(CONNECTION_URL)

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "status": "error",
            "provider": "omnidimension",
            "message": "OmniDimension connection check failed.",
        }
    }
    assert "test-secret" not in response.text
    assert "sensitive provider response" not in response.text
