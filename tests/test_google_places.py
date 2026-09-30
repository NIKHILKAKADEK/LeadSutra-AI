"""Comprehensive unit tests for GooglePlacesProvider.

Covers:
 1. Successful search and field mapping to normalised BusinessLead.
 2. Rating filtering (rating >= minimum_rating).
 3. Handling empty search results.
 4. Malformed JSON response handling (GoogleAPIMalformedResponseError).
 5. Authentication failure (GoogleAPIAuthenticationError) on 401/403.
 6. Quota / rate-limit failure (GoogleAPIQuotaError) on 429.
 7. Timeout handling (GoogleAPITimeoutError).
 8. Server error (GoogleAPIUnavailableError) on 500/503.
 9. Verification that API key is NEVER logged.
10. Integration test marker for real Google Places API requests.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from dotenv import load_dotenv

from app.models.lead import BusinessLead
from app.services.lead_discovery.exceptions import (
    GoogleAPIAuthenticationError,
    GoogleAPIMalformedResponseError,
    GoogleAPIQuotaError,
    GoogleAPITimeoutError,
    GoogleAPIUnavailableError,
    GooglePlacesAPIError,
)
from app.services.lead_discovery.google_places import (
    FIELD_MASK,
    PLACES_TEXT_SEARCH_URL,
    GooglePlacesProvider,
    _mask_key,
)


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SAMPLE_PLACE: dict[str, Any] = {
    "id": "ChIJsample_001",
    "displayName": {"text": "The Grand Cafe"},
    "formattedAddress": "42 MG Road, Nashik, Maharashtra 422001",
    "primaryType": "cafe",
    "rating": 4.3,
    "userRatingCount": 85,
    "nationalPhoneNumber": "+91 98765 43210",
    "websiteUri": "https://grandcafe.example.com",
    "location": {"latitude": 20.0059, "longitude": 73.7797},
}

LOW_RATED_PLACE: dict[str, Any] = {
    "id": "ChIJsample_002",
    "displayName": {"text": "Budget Snacks"},
    "formattedAddress": "1 Old Road, Nashik",
    "primaryType": "snack_bar",
    "rating": 2.1,
    "location": {"latitude": 19.99, "longitude": 73.77},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_provider(api_key: str = "test-api-key", **kwargs: Any) -> GooglePlacesProvider:
    """Return a ``GooglePlacesProvider`` with the given key (no dotenv lookup)."""
    return GooglePlacesProvider(api_key=api_key, **kwargs)


def make_response(status: int, body: Any) -> httpx.Response:
    """Build a minimal ``httpx.Response`` for mocking."""
    if isinstance(body, (dict, list)):
        return httpx.Response(status, json=body)
    # For malformed / non-JSON payloads pass raw bytes
    return httpx.Response(status, content=body)


class _AsyncClientMock:
    """Async context-manager that records POST calls."""

    def __init__(self, response: httpx.Response | Exception, recorded: list[dict[str, Any]]) -> None:
        self._response = response
        self._recorded = recorded

    async def __aenter__(self) -> "_AsyncClientMock":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self._recorded.append({"url": url, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def patch_httpx(monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception) -> list[dict[str, Any]]:
    """Patch ``httpx.AsyncClient`` inside ``google_places`` module."""
    recorded: list[dict[str, Any]] = []
    import app.services.lead_discovery.google_places as _gp

    monkeypatch.setattr(
        _gp.httpx,
        "AsyncClient",
        lambda **_: _AsyncClientMock(response, recorded),
    )
    return recorded


# ---------------------------------------------------------------------------
# 1. Successful search and field mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_search_returns_business_leads(monkeypatch: pytest.MonkeyPatch) -> None:
    """1. A 200 response maps all available fields to a normalised BusinessLead."""
    recorded = patch_httpx(monkeypatch, make_response(200, {"places": [SAMPLE_PLACE]}))
    provider = make_provider()

    results = await provider.search("cafe", "Nashik, Maharashtra")

    assert len(results) == 1
    lead = results[0]

    assert isinstance(lead, BusinessLead)
    assert lead.source == "google"
    assert lead.external_place_id == "ChIJsample_001"
    assert lead.name == "The Grand Cafe"
    assert lead.category == "cafe"
    assert lead.rating == pytest.approx(4.3)
    assert lead.phone == "+91 98765 43210"
    assert lead.website == "https://grandcafe.example.com"
    assert lead.address == "42 MG Road, Nashik, Maharashtra 422001"
    assert lead.latitude == pytest.approx(20.0059)
    assert lead.longitude == pytest.approx(73.7797)

    # Verify correct HTTP request was made
    assert len(recorded) == 1
    req = recorded[0]
    assert req["url"] == PLACES_TEXT_SEARCH_URL
    assert req["json"]["textQuery"] == "cafe in Nashik, Maharashtra"
    assert req["headers"]["X-Goog-FieldMask"] == FIELD_MASK
    assert req["headers"]["X-Goog-Api-Key"] == "test-api-key"


@pytest.mark.asyncio
async def test_field_mask_is_not_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """The field mask must never be the wildcard '*' to avoid over-fetching."""
    patch_httpx(monkeypatch, make_response(200, {}))
    provider = make_provider()
    await provider.search("restaurant", "Mumbai")
    assert FIELD_MASK != "*"
    assert "places.id" in FIELD_MASK
    assert "places.displayName" in FIELD_MASK


# ---------------------------------------------------------------------------
# 2. Rating filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rating_filter_removes_low_rated_leads(monkeypatch: pytest.MonkeyPatch) -> None:
    """2. Leads below minimum_rating are excluded from results."""
    body = {"places": [SAMPLE_PLACE, LOW_RATED_PLACE]}
    patch_httpx(monkeypatch, make_response(200, body))
    provider = make_provider(minimum_rating=4.0)

    results = await provider.search("cafe", "Nashik")

    assert len(results) == 1
    assert results[0].name == "The Grand Cafe"


@pytest.mark.asyncio
async def test_rating_filter_includes_equal_to_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    """2b. A lead with rating exactly equal to minimum_rating is included."""
    place = {**SAMPLE_PLACE, "rating": 4.0}
    patch_httpx(monkeypatch, make_response(200, {"places": [place]}))
    provider = make_provider(minimum_rating=4.0)

    results = await provider.search("cafe", "Nashik")

    assert len(results) == 1


@pytest.mark.asyncio
async def test_lead_with_no_rating_is_included_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """2c. Leads with no rating (None) pass the rating filter."""
    place = {k: v for k, v in SAMPLE_PLACE.items() if k != "rating"}
    patch_httpx(monkeypatch, make_response(200, {"places": [place]}))
    provider = make_provider(minimum_rating=3.0)

    results = await provider.search("cafe", "Nashik")

    assert len(results) == 1
    assert results[0].rating is None


# ---------------------------------------------------------------------------
# 3. Empty results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_places_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """3. When the API returns no places the provider returns an empty list."""
    patch_httpx(monkeypatch, make_response(200, {}))
    provider = make_provider()

    results = await provider.search("unicorn", "Nashik")

    assert results == []


@pytest.mark.asyncio
async def test_empty_places_key_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """3b. An explicit empty 'places' list also returns an empty list."""
    patch_httpx(monkeypatch, make_response(200, {"places": []}))
    provider = make_provider()

    results = await provider.search("unicorn", "Nashik")

    assert results == []


# ---------------------------------------------------------------------------
# 4. Malformed JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_json_raises_malformed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """4. A response that cannot be parsed raises GoogleAPIMalformedResponseError."""
    patch_httpx(monkeypatch, make_response(200, b"not-json!!!"))
    provider = make_provider()

    with pytest.raises(GoogleAPIMalformedResponseError):
        await provider.search("cafe", "Nashik")


# ---------------------------------------------------------------------------
# 5. Authentication failures (401 / 403)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_auth_failure_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """5. HTTP 401/403 raises GoogleAPIAuthenticationError."""
    patch_httpx(monkeypatch, make_response(status_code, {"error": "UNAUTHENTICATED"}))
    provider = make_provider()

    with pytest.raises(GoogleAPIAuthenticationError) as exc_info:
        await provider.search("cafe", "Nashik")

    assert exc_info.value.status_code == status_code
    assert "HTTP error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. Quota / rate-limit (429)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_raises_quota_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """6. HTTP 429 raises GoogleAPIQuotaError."""
    patch_httpx(monkeypatch, make_response(429, {"error": "RESOURCE_EXHAUSTED"}))
    provider = make_provider()

    with pytest.raises(GoogleAPIQuotaError) as exc_info:
        await provider.search("cafe", "Nashik")

    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# 7. Timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_raises_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """7. A network timeout raises GoogleAPITimeoutError with a descriptive message."""
    patch_httpx(monkeypatch, httpx.ReadTimeout("connection timed out"))
    provider = make_provider()

    with pytest.raises(GoogleAPITimeoutError, match="timed out"):
        await provider.search("cafe", "Nashik")


# ---------------------------------------------------------------------------
# 8. Server errors (500 / 502 / 503 / 504)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
async def test_server_error_raises_unavailable_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """8. HTTP 5xx raises GoogleAPIUnavailableError."""
    patch_httpx(monkeypatch, make_response(status_code, {}))
    provider = make_provider()

    with pytest.raises(GoogleAPIUnavailableError) as exc_info:
        await provider.search("cafe", "Nashik")

    assert exc_info.value.status_code == status_code


# ---------------------------------------------------------------------------
# 9. API key security — never logged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_never_appears_in_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """9. The raw API key must not appear in any log record at any level."""
    api_key = "super-secret-api-key-xyz-9999"
    patch_httpx(monkeypatch, make_response(200, {"places": [SAMPLE_PLACE]}))
    provider = make_provider(api_key=api_key)

    with caplog.at_level(logging.DEBUG):
        await provider.search("cafe", "Nashik")

    assert api_key not in caplog.text


@pytest.mark.asyncio
async def test_api_key_not_in_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """9b. The raw API key must not appear in exception messages."""
    api_key = "secret-key-do-not-leak"
    patch_httpx(monkeypatch, make_response(403, {}))
    provider = make_provider(api_key=api_key)

    with pytest.raises(GoogleAPIAuthenticationError) as exc_info:
        await provider.search("cafe", "Nashik")

    assert api_key not in str(exc_info.value)


def test_mask_key_helper_masks_long_key() -> None:
    """9c. The _mask_key helper returns a safe representation."""
    key = "AIzaSyAbcdefghij1234"
    masked = _mask_key(key)
    assert "AIza" in masked       # prefix visible
    assert "1234" in masked       # suffix visible
    assert key not in masked      # full key not present


def test_mask_key_helper_short_key() -> None:
    """9d. Short keys are fully masked."""
    assert _mask_key("short") == "****"


# ---------------------------------------------------------------------------
# Validation — empty query / location
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "location"), [("", "Nashik"), ("cafe", ""), ("  ", "Nashik")])
async def test_empty_params_raise_value_error(
    monkeypatch: pytest.MonkeyPatch, query: str, location: str
) -> None:
    """Empty or whitespace-only query or location raises ValueError before HTTP."""
    recorded = patch_httpx(monkeypatch, make_response(200, {}))
    provider = make_provider()

    with pytest.raises(ValueError):
        await provider.search(query, location)

    assert recorded == []


# ---------------------------------------------------------------------------
# Limit parameter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_limit_is_capped_at_20(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Google API caps pageSize at 20; larger limits are silently clamped."""
    recorded = patch_httpx(monkeypatch, make_response(200, {}))
    provider = make_provider()

    await provider.search("cafe", "Nashik", limit=100)

    assert recorded[0]["json"]["pageSize"] == 20


@pytest.mark.asyncio
async def test_limit_respects_smaller_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A limit smaller than 20 is passed through unchanged."""
    recorded = patch_httpx(monkeypatch, make_response(200, {}))
    provider = make_provider()

    await provider.search("cafe", "Nashik", limit=5)

    assert recorded[0]["json"]["pageSize"] == 5


# ---------------------------------------------------------------------------
# 10. Integration test (real API key required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_google_places_request() -> None:
    """10. Optional live integration test against the real Google Places API."""
    load_dotenv()
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_MAPS_API_KEY is not configured.")

    provider = GooglePlacesProvider(api_key=api_key)
    results = await provider.search("restaurant", "Nashik, Maharashtra", limit=5)

    assert isinstance(results, list)
    print(f"\nLive API returned {len(results)} result(s).")
    for lead in results:
        assert isinstance(lead, BusinessLead)
        assert lead.name
        assert lead.source == "google"
        print(f"  • {lead.name} — rating={lead.rating}, address={lead.address}")
