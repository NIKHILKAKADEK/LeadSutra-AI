"""Comprehensive unit and integration tests for FoursquarePlacesProvider (Task 2).

Covers:
 TEST 1: Successful Foursquare search and field mapping.
 TEST 2: Correct conversion of Foursquare rating (8.0/10 -> 4.0/5, 8.6/10 -> 4.3/5).
 TEST 3: Minimum rating filtering (minimum_rating=4.0: 8.5/10 retained, 7.9/10 rejected).
 TEST 4: Missing rating handling (null rating passes or handled safely).
 TEST 5: Missing phone handling (tel=None yields phone=None).
 TEST 6: Missing website handling (website=None yields website=None).
 TEST 7: Missing email handling (email=None yields email=None).
 TEST 8: Empty search results (empty results array returns []).
 TEST 9: Invalid API key / authentication failure (401/403 raises FoursquareAPIAuthenticationError).
 TEST 10: Rate limit / quota failure (429 raises FoursquareAPIQuotaError).
 TEST 11: Timeout / network failure (raises FoursquareAPITimeoutError).
 TEST 12: Output matches common LeadSutra BusinessLead schema (source="foursquare").
 TEST 13: Security check: API key is NEVER logged or exposed in exceptions.
 TEST 14: Live integration test marker (@pytest.mark.integration).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import pytest
from dotenv import load_dotenv

from app.models.lead import BusinessLead
from app.services.lead_discovery.exceptions import (
    FoursquareAPIAuthenticationError,
    FoursquareAPIMalformedResponseError,
    FoursquareAPIQuotaError,
    FoursquareAPITimeoutError,
    FoursquareAPIUnavailableError,
    FoursquarePlacesAPIError,
)
from app.services.lead_discovery.foursquare_places import (
    FOURSQUARE_FIELDS,
    FOURSQUARE_SEARCH_URL,
    FoursquarePlacesProvider,
    _mask_key,
)


# ---------------------------------------------------------------------------
# Test Data Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FSQ_PLACE: dict[str, Any] = {
    "fsq_place_id": "4b5d4e1cf964a520c15929e3",
    "name": "Spice Route Restaurant",
    "rating": 8.6,
    "tel": "+91 253 231 1111",
    "email": "contact@spiceroute.example.com",
    "website": "https://spiceroute.example.com",
    "location": {
        "formatted_address": "College Road, Nashik, Maharashtra 422005",
        "latitude": 20.0083,
        "longitude": 73.7639,
    },
    "categories": [
        {"id": 13065, "name": "Indian Restaurant"}
    ],
    "geocodes": {
        "main": {"latitude": 20.0083, "longitude": 73.7639}
    },
}

LOW_RATED_FSQ_PLACE: dict[str, Any] = {
    "fsq_place_id": "4b5d4e1cf964a520c15929e4",
    "name": "Fast Bites Canteen",
    "rating": 7.4,  # 7.4 / 2 = 3.7 (< 4.0 threshold)
    "tel": "+91 253 231 2222",
    "email": "info@fastbites.example.com",
    "website": "https://fastbites.example.com",
    "location": {"formatted_address": "Station Road, Nashik"},
    "categories": [{"id": 13000, "name": "Fast Food Restaurant"}],
}

HIGH_RATED_FSQ_PLACE: dict[str, Any] = {
    "fsq_place_id": "4b5d4e1cf964a520c15929e5",
    "name": "Royal Fine Dining",
    "rating": 8.5,  # 8.5 / 2 = 4.25 (>= 4.0 threshold)
    "tel": "+91 253 231 3333",
    "email": "reserve@royaldining.example.com",
    "website": "https://royaldining.example.com",
    "location": {"formatted_address": "MG Road, Nashik"},
    "categories": [{"id": 13000, "name": "Fine Dining"}],
}


# ---------------------------------------------------------------------------
# Mock Helpers
# ---------------------------------------------------------------------------

class _AsyncClientMock:
    """Async context-manager that records GET calls."""

    def __init__(self, response: httpx.Response | Exception, recorded: list[dict[str, Any]]) -> None:
        self._response = response
        self._recorded = recorded

    async def __aenter__(self) -> "_AsyncClientMock":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self._recorded.append({"url": url, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def patch_httpx(monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception) -> list[dict[str, Any]]:
    """Patch ``httpx.AsyncClient`` inside ``foursquare_places`` module."""
    recorded: list[dict[str, Any]] = []
    import app.services.lead_discovery.foursquare_places as _fsq

    monkeypatch.setattr(
        _fsq.httpx,
        "AsyncClient",
        lambda **_: _AsyncClientMock(response, recorded),
    )
    return recorded


def make_provider(api_key: str = "test-fsq-key", **kwargs: Any) -> FoursquarePlacesProvider:
    """Return a ``FoursquarePlacesProvider`` with explicit test key."""
    return FoursquarePlacesProvider(api_key=api_key, **kwargs)


def make_response(status: int, body: Any) -> httpx.Response:
    """Build a minimal ``httpx.Response`` for mocking."""
    if isinstance(body, (dict, list)):
        return httpx.Response(status, json=body)
    return httpx.Response(status, content=body)


# ---------------------------------------------------------------------------
# TEST 1: Successful Search & Field Mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_foursquare_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 1: Valid search returns normalized BusinessLead with mapped Foursquare fields."""
    recorded = patch_httpx(monkeypatch, make_response(200, {"results": [SAMPLE_FSQ_PLACE]}))
    provider = make_provider()

    results = await provider.search("restaurant", "Nashik, Maharashtra")

    assert len(results) == 1
    lead = results[0]

    assert isinstance(lead, BusinessLead)
    assert lead.external_place_id == "4b5d4e1cf964a520c15929e3"
    assert lead.source == "foursquare"
    assert lead.name == "Spice Route Restaurant"
    assert lead.category == "Indian Restaurant"
    assert lead.rating == 4.3  # 8.6 / 2
    assert lead.phone == "+91 253 231 1111"
    assert lead.email == "contact@spiceroute.example.com"
    assert lead.website == "https://spiceroute.example.com"
    assert lead.address == "College Road, Nashik, Maharashtra 422005"
    assert lead.latitude == pytest.approx(20.0083)
    assert lead.longitude == pytest.approx(73.7639)

    # Verify request headers & params
    assert len(recorded) == 1
    req = recorded[0]
    assert req["url"] == FOURSQUARE_SEARCH_URL
    assert req["headers"]["Authorization"] == "Bearer test-fsq-key"
    assert req["params"]["query"] == "restaurant"
    assert req["params"]["near"] == "Nashik, Maharashtra"
    assert req["params"]["fields"] == FOURSQUARE_FIELDS


# ---------------------------------------------------------------------------
# TEST 2: Rating Conversion (0–10 scale -> 0–5 scale)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fsq_rating", "expected_rating_5"),
    [
        (8.0, 4.0),
        (8.6, 4.3),
        (10.0, 5.0),
        (5.0, 2.5),
        (0.0, 0.0),
    ],
)
async def test_rating_conversion(
    monkeypatch: pytest.MonkeyPatch, fsq_rating: float, expected_rating_5: float
) -> None:
    """TEST 2: Correct conversion of Foursquare 0–10 rating scale to 0–5 scale."""
    place = {**SAMPLE_FSQ_PLACE, "rating": fsq_rating}
    patch_httpx(monkeypatch, make_response(200, {"results": [place]}))
    provider = make_provider()

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    assert results[0].rating == expected_rating_5


# ---------------------------------------------------------------------------
# TEST 3: Minimum Rating Filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_minimum_rating_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 3: minimum_rating=4.0 retains 8.5/10 (4.25) and rejects 7.4/10 (3.7)."""
    body = {"results": [HIGH_RATED_FSQ_PLACE, LOW_RATED_FSQ_PLACE]}
    patch_httpx(monkeypatch, make_response(200, body))
    provider = make_provider(minimum_rating=4.0)

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    assert results[0].name == "Royal Fine Dining"
    assert results[0].rating == 4.2  # 8.5 / 2 = 4.25 rounded to 4.2


# ---------------------------------------------------------------------------
# TEST 4: Missing Rating Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_rating_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 4: A lead with null rating is safely converted to rating=None and retained."""
    place = {k: v for k, v in SAMPLE_FSQ_PLACE.items() if k != "rating"}
    patch_httpx(monkeypatch, make_response(200, {"results": [place]}))
    provider = make_provider(minimum_rating=3.0)

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    assert results[0].rating is None


# ---------------------------------------------------------------------------
# TEST 5: Missing Phone Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_phone_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 5: Missing 'tel' in Foursquare response yields phone=None."""
    place = {k: v for k, v in SAMPLE_FSQ_PLACE.items() if k != "tel"}
    patch_httpx(monkeypatch, make_response(200, {"results": [place]}))
    provider = make_provider()

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    assert results[0].phone is None


# ---------------------------------------------------------------------------
# TEST 6: Missing Website Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_website_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 6: Missing 'website' in Foursquare response yields website=None."""
    place = {k: v for k, v in SAMPLE_FSQ_PLACE.items() if k != "website"}
    patch_httpx(monkeypatch, make_response(200, {"results": [place]}))
    provider = make_provider()

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    assert results[0].website is None


# ---------------------------------------------------------------------------
# TEST 7: Missing Email Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_email_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 7: Missing 'email' in Foursquare response yields email=None."""
    place = {k: v for k, v in SAMPLE_FSQ_PLACE.items() if k != "email"}
    patch_httpx(monkeypatch, make_response(200, {"results": [place]}))
    provider = make_provider()

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    assert results[0].email is None


# ---------------------------------------------------------------------------
# TEST 8: Empty Search Results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_search_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 8: API returning empty 'results' list returns an empty python list."""
    patch_httpx(monkeypatch, make_response(200, {"results": []}))
    provider = make_provider()

    results = await provider.search("nonexistent_category", "Nashik")

    assert results == []


# ---------------------------------------------------------------------------
# TEST 9: Invalid API Key / Auth Failure (401/403)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_auth_failure_raises_exception(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """TEST 9: HTTP 401/403 raises FoursquareAPIAuthenticationError."""
    patch_httpx(monkeypatch, make_response(status_code, {"error": "Unauthorized"}))
    provider = make_provider()

    with pytest.raises(FoursquareAPIAuthenticationError) as exc_info:
        await provider.search("restaurant", "Nashik")

    assert exc_info.value.status_code == status_code


# ---------------------------------------------------------------------------
# TEST 10: Rate Limit / Quota Failure (429)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quota_exhaustion_raises_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 10: HTTP 429 raises FoursquareAPIQuotaError."""
    patch_httpx(monkeypatch, make_response(429, {"error": "Quota Exceeded"}))
    provider = make_provider()

    with pytest.raises(FoursquareAPIQuotaError) as exc_info:
        await provider.search("restaurant", "Nashik")

    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# TEST 11: Timeout / Network Failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_raises_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 11: ReadTimeout raises FoursquareAPITimeoutError."""
    patch_httpx(monkeypatch, httpx.ReadTimeout("connection timed out"))
    provider = make_provider()

    with pytest.raises(FoursquareAPITimeoutError, match="timed out"):
        await provider.search("restaurant", "Nashik")


# ---------------------------------------------------------------------------
# TEST 12: Verify Output Matches Common LeadSutra Schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_matches_common_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 12: Output objects are instances of BusinessLead with source="foursquare"."""
    patch_httpx(monkeypatch, make_response(200, {"results": [SAMPLE_FSQ_PLACE]}))
    provider = make_provider()

    results = await provider.search("restaurant", "Nashik")

    assert len(results) == 1
    lead = results[0]

    assert isinstance(lead, BusinessLead)
    assert lead.source == "foursquare"

    # Export dictionary check
    d = lead.to_dict()
    assert d["source"] == "foursquare"
    assert "external_place_id" in d
    assert "name" in d
    assert "category" in d
    assert "rating" in d
    assert "phone" in d
    assert "email" in d
    assert "website" in d
    assert "address" in d
    assert "latitude" in d
    assert "longitude" in d


# ---------------------------------------------------------------------------
# TEST 13: API Key Security
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """TEST 13: Raw Foursquare API key is never logged or present in exception text."""
    secret_key = "fsq3_secret_api_key_99999"
    patch_httpx(monkeypatch, make_response(200, {"results": [SAMPLE_FSQ_PLACE]}))
    provider = make_provider(api_key=secret_key)

    with caplog.at_level(logging.DEBUG):
        await provider.search("restaurant", "Nashik")

    assert secret_key not in caplog.text


@pytest.mark.asyncio
async def test_api_key_not_in_exception_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST 13b: Raw Foursquare API key is never present in exception string representations."""
    secret_key = "fsq3_secret_key_leak_check"
    patch_httpx(monkeypatch, make_response(401, {"error": "Unauthorized"}))
    provider = make_provider(api_key=secret_key)

    with pytest.raises(FoursquareAPIAuthenticationError) as exc_info:
        await provider.search("restaurant", "Nashik")

    assert secret_key not in str(exc_info.value)


def test_mask_key_helper() -> None:
    """TEST 13c: Key masking helper masks sensitive credentials cleanly."""
    assert "fsq3" in _mask_key("fsq3_123456789")
    assert "6789" in _mask_key("fsq3_123456789")
    assert "fsq3_123456789" not in _mask_key("fsq3_123456789")
    assert _mask_key("short") == "****"


# ---------------------------------------------------------------------------
# Server Error (5xx) & Malformed JSON Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503])
async def test_server_error_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """HTTP 5xx raises FoursquareAPIUnavailableError."""
    patch_httpx(monkeypatch, make_response(status_code, {}))
    provider = make_provider()

    with pytest.raises(FoursquareAPIUnavailableError) as exc_info:
        await provider.search("restaurant", "Nashik")

    assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
async def test_malformed_json_raises_malformed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-JSON response raises FoursquareAPIMalformedResponseError."""
    patch_httpx(monkeypatch, make_response(200, b"invalid-non-json-content"))
    provider = make_provider()

    with pytest.raises(FoursquareAPIMalformedResponseError):
        await provider.search("restaurant", "Nashik")


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "location"), [("", "Nashik"), ("restaurant", ""), ("  ", "Nashik")])
async def test_empty_query_or_location_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, query: str, location: str
) -> None:
    """Blank query or location raises ValueError before HTTP request."""
    recorded = patch_httpx(monkeypatch, make_response(200, {"results": []}))
    provider = make_provider()

    with pytest.raises(ValueError):
        await provider.search(query, location)

    assert recorded == []


# ---------------------------------------------------------------------------
# TEST 14: Live Integration Test (Requires FOURSQUARE_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_foursquare_places_request() -> None:
    """TEST 14: Live integration test against real Foursquare Places API."""
    load_dotenv()
    api_key = os.getenv("FOURSQUARE_API_KEY")
    if not api_key:
        pytest.skip("FOURSQUARE_API_KEY is not configured in environment.")

    provider = FoursquarePlacesProvider(api_key=api_key)
    results = await provider.search("restaurant", "Nashik, Maharashtra", limit=5)

    assert isinstance(results, list)
    print(f"\nLive Foursquare API returned {len(results)} result(s).")
    for lead in results:
        assert isinstance(lead, BusinessLead)
        assert lead.name
        assert lead.source == "foursquare"
        print(f"  • {lead.name} — rating={lead.rating}, phone={lead.phone}, address={lead.address}")
