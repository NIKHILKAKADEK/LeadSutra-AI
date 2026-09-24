"""Focused tests for the Google Places business search service.

These tests verify the behaviour of the ``maps_search`` compatibility
shim (``app.agents.lead_discovery.maps_search``) which in turn delegates
to ``app.services.lead_discovery``.  The shim must be the import target
so that ``monkeypatch`` can intercept ``httpx.AsyncClient`` at the right
location.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import pytest
from dotenv import load_dotenv

from app.agents.lead_discovery import maps_search


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

# A minimal Google Places API place object as returned by the Text Search
# endpoint.  Field names match the Google Places (New) schema.
GOOGLE_PLACE = {
    "id": "ChIJexample12345",
    "displayName": {"text": "Example Cafe"},
    "formattedAddress": "1 Main Street, Nashik, Maharashtra",
    "primaryType": "cafe",
    "rating": 4.5,
    "userRatingCount": 120,
    "nationalPhoneNumber": "+91 9876543210",
    "websiteUri": "https://example-cafe.com",
    "location": {"latitude": 19.9975, "longitude": 73.7898},
}


class MockAsyncClient:
    """Minimal async HTTP client replacement that records requests."""

    def __init__(self, response: httpx.Response | Exception, requests: list[dict[str, Any]], **_: Any) -> None:
        self.response = response
        self.requests = requests

    async def __aenter__(self) -> "MockAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append({"method": "POST", "url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append({"method": "GET", "url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def mock_google_response(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception
) -> list[dict[str, Any]]:
    """Replace ``httpx.AsyncClient`` inside *maps_search* with a mock."""
    requests: list[dict[str, Any]] = []
    monkeypatch.setattr(
        maps_search.httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(response, requests, **kwargs),
    )
    return requests


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_is_loaded_from_dotenv(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The service loads GOOGLE_MAPS_API_KEY from a project .env file."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GOOGLE_MAPS_API_KEY=key-from-dotenv\n", encoding="utf-8")
    requests = mock_google_response(monkeypatch, httpx.Response(200, json={}))

    # Reset the cached default service so it picks up the new env variable.
    import app.services.lead_discovery.search_service as _svc
    _svc._default_service = None

    await maps_search.search_businesses("cafe", "Nashik")

    assert requests[0]["headers"]["X-Goog-Api-Key"] == "key-from-dotenv"


@pytest.mark.asyncio
async def test_valid_search_returns_parsed_businesses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid search returns normalised BusinessLead objects with correct fields."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    requests = mock_google_response(
        monkeypatch, httpx.Response(200, json={"places": [GOOGLE_PLACE]})
    )

    import app.services.lead_discovery.search_service as _svc
    _svc._default_service = None

    businesses = await maps_search.search_businesses("cafe", "Nashik, Maharashtra")

    assert len(businesses) == 1
    lead = businesses[0]

    # Field mapping assertions (normalised BusinessLead schema)
    assert lead.name == "Example Cafe"
    assert lead.address == "1 Main Street, Nashik, Maharashtra"
    assert lead.category == "cafe"
    assert lead.rating == 4.5
    assert lead.source == "google"
    assert lead.external_place_id == "ChIJexample12345"
    assert lead.phone == "+91 9876543210"
    assert lead.website == "https://example-cafe.com"
    assert lead.latitude == pytest.approx(19.9975)
    assert lead.longitude == pytest.approx(73.7898)

    # HTTP request assertions
    assert len(requests) == 1
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == maps_search.PLACES_TEXT_SEARCH_URL
    assert requests[0]["json"] == {"textQuery": "cafe in Nashik, Maharashtra", "pageSize": 20}
    assert requests[0]["headers"]["X-Goog-FieldMask"] == maps_search.FIELD_MASK
    assert requests[0]["headers"]["X-Goog-FieldMask"] != "*"


@pytest.mark.asyncio
async def test_invalid_api_key_is_handled_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google rejecting a key produces a safe error without exposing the key."""
    api_key = "invalid-test-key"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", api_key)
    request = httpx.Request("POST", maps_search.PLACES_TEXT_SEARCH_URL)
    mock_google_response(monkeypatch, httpx.Response(403, request=request))

    import app.services.lead_discovery.search_service as _svc
    _svc._default_service = None

    with pytest.raises((maps_search.MapsAPIError, maps_search.LeadDiscoveryError)) as error:
        await maps_search.search_businesses("cafe", "Nashik")

    assert api_key not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(("category", "location"), [("", "Nashik"), ("cafe", "")])
async def test_invalid_category_or_location_is_rejected(
    monkeypatch: pytest.MonkeyPatch, category: str, location: str
) -> None:
    """Empty category or location fails before any HTTP request is made."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    requests = mock_google_response(monkeypatch, httpx.Response(200, json={}))

    import app.services.lead_discovery.search_service as _svc
    _svc._default_service = None

    with pytest.raises(ValueError):
        await maps_search.search_businesses(category, location)

    assert requests == []


@pytest.mark.asyncio
async def test_google_timeout_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A network timeout raises a clear application-level error."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    mock_google_response(monkeypatch, httpx.ReadTimeout("timed out"))

    import app.services.lead_discovery.search_service as _svc
    _svc._default_service = None

    with pytest.raises((maps_search.MapsAPIError, maps_search.LeadDiscoveryError)):
        await maps_search.search_businesses("cafe", "Nashik")


@pytest.mark.asyncio
async def test_api_key_never_appears_in_logs(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """The service must not log the configured API key at any log level."""
    api_key = "private-test-key"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", api_key)
    mock_google_response(monkeypatch, httpx.Response(200, json={}))

    import app.services.lead_discovery.search_service as _svc
    _svc._default_service = None

    with caplog.at_level(logging.DEBUG):
        await maps_search.search_businesses("cafe", "Nashik")

    assert api_key not in caplog.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_places_returns_results_with_configured_key() -> None:
    """Optional integration test: performs a real Google Places API request."""
    load_dotenv()
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key or "your_" in api_key.lower() or "placeholder" in api_key.lower():
        pytest.skip("GOOGLE_MAPS_API_KEY is not configured.")

    try:
        businesses = await maps_search.search_businesses("restaurant", "Nashik, Maharashtra")
    except (maps_search.MapsAPIError, maps_search.LeadDiscoveryError) as exc:
        pytest.skip(f"GOOGLE_MAPS_API_KEY is not valid or live API request failed: {exc}")

    assert isinstance(businesses, list)
    print(f"Google Places request succeeded; results: {len(businesses)}")
    if businesses:
        lead = businesses[0]
        print(f"First business: {lead.name}")
        assert lead.name
