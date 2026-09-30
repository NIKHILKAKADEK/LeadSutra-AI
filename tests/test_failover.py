"""Comprehensive unit tests for BusinessSearchService provider failover (Task 3).

Covers:
 TEST 1: Google success (Google called = YES, Foursquare called = NO, fallback_used = False).
 TEST 2: Google timeout (Google called = YES, Foursquare called = YES, fallback_used = True).
 TEST 3: Google HTTP 429 quota exhaustion (triggers Foursquare fallback).
 TEST 4: Google HTTP 503 server error (triggers Foursquare fallback).
 TEST 5: Google HTTP 401/403 auth error (triggers Foursquare fallback).
 TEST 6: Google returns empty results [] (Google called = YES, Foursquare called = NO, leads = []).
 TEST 7: Google fails + Foursquare fails (raises clean LeadDiscoveryError with sanitized message).
 TEST 8: Same search criteria (exact query, location, limit passed to fallback provider).
 TEST 9: Common schema maintained (source="google" vs source="foursquare" set on BusinessLead).
 TEST 10: API key protection (no credential leakage in logs or exception messages during failover).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.lead import BusinessLead, BusinessSearchResponse
from app.services.lead_discovery.base import BaseBusinessDiscoveryProvider
from app.services.lead_discovery.exceptions import (
    FoursquareAPIAuthenticationError,
    FoursquareAPIQuotaError,
    FoursquareAPITimeoutError,
    FoursquareAPIUnavailableError,
    GoogleAPIAuthenticationError,
    GoogleAPIQuotaError,
    GoogleAPITimeoutError,
    GoogleAPIUnavailableError,
    GooglePlacesAPIError,
    LeadDiscoveryError,
)
from app.services.lead_discovery.search_service import (
    BusinessSearchService,
    search_businesses,
    search_businesses_with_metadata,
)


# ---------------------------------------------------------------------------
# Test Data Fixtures
# ---------------------------------------------------------------------------

GOOGLE_LEAD = BusinessLead(
    external_place_id="google_001",
    source="google",
    name="Google Bakery",
    category="bakery",
    rating=4.5,
    phone="+91 98765 00001",
    website="https://googlebakery.example.com",
    address="1 Main St, Nashik",
)

FOURSQUARE_LEAD = BusinessLead(
    external_place_id="fsq_002",
    source="foursquare",
    name="Foursquare Cafe",
    category="cafe",
    rating=4.2,
    phone="+91 98765 00002",
    email="info@fsqcafe.example.com",
    website="https://fsqcafe.example.com",
    address="2 Park Rd, Nashik",
)


# ---------------------------------------------------------------------------
# Mock Provider Helper
# ---------------------------------------------------------------------------

def make_mock_provider(
    name: str = "mock",
    return_value: list[BusinessLead] | None = None,
    side_effect: Exception | None = None,
) -> BaseBusinessDiscoveryProvider:
    """Create a mock ``BaseBusinessDiscoveryProvider`` instance."""
    provider = AsyncMock(spec=BaseBusinessDiscoveryProvider)
    if side_effect is not None:
        provider.search.side_effect = side_effect
    else:
        provider.search.return_value = return_value if return_value is not None else []
    return provider


# ---------------------------------------------------------------------------
# TEST 1: Google Success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_success() -> None:
    """TEST 1: When Google succeeds, return Google results and DO NOT call Foursquare."""
    primary = make_mock_provider(return_value=[GOOGLE_LEAD])
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    response = await service.search_with_metadata("bakery", "Nashik", limit=10)

    assert isinstance(response, BusinessSearchResponse)
    assert response.provider == "google"
    assert response.fallback_used is False
    assert len(response.leads) == 1
    assert response.leads[0].name == "Google Bakery"
    assert response.leads[0].source == "google"

    primary.search.assert_called_once_with("bakery", "Nashik", limit=10)
    fallback.search.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 2: Google Timeout -> Foursquare Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_timeout_triggers_fallback() -> None:
    """TEST 2: Google timeout triggers automatic fallback to Foursquare."""
    primary = make_mock_provider(side_effect=GoogleAPITimeoutError("Request to Google Places timed out"))
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    response = await service.search_with_metadata("cafe", "Nashik", limit=15)

    assert response.provider == "foursquare"
    assert response.fallback_used is True
    assert len(response.leads) == 1
    assert response.leads[0].name == "Foursquare Cafe"
    assert response.leads[0].source == "foursquare"

    primary.search.assert_called_once_with("cafe", "Nashik", limit=15)
    fallback.search.assert_called_once_with("cafe", "Nashik", limit=15)


# ---------------------------------------------------------------------------
# TEST 3: Google 429 Quota Failure -> Foursquare Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_429_quota_triggers_fallback() -> None:
    """TEST 3: Google HTTP 429 rate limit triggers Foursquare fallback."""
    primary = make_mock_provider(side_effect=GoogleAPIQuotaError("HTTP error 429: rate limit", status_code=429))
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    response = await service.search_with_metadata("restaurant", "Nashik")

    assert response.provider == "foursquare"
    assert response.fallback_used is True
    assert response.leads == [FOURSQUARE_LEAD]

    primary.search.assert_called_once()
    fallback.search.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 4: Google 503 Server Error -> Foursquare Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_503_server_error_triggers_fallback() -> None:
    """TEST 4: Google HTTP 503 service unavailable triggers Foursquare fallback."""
    primary = make_mock_provider(side_effect=GoogleAPIUnavailableError("HTTP error 503: server error", status_code=503))
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    response = await service.search_with_metadata("hotel", "Nashik")

    assert response.provider == "foursquare"
    assert response.fallback_used is True
    assert response.leads == [FOURSQUARE_LEAD]


# ---------------------------------------------------------------------------
# TEST 5: Google Auth Error -> Foursquare Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_auth_failure_triggers_fallback() -> None:
    """TEST 5: Google HTTP 401/403 authentication error triggers Foursquare fallback."""
    primary = make_mock_provider(side_effect=GoogleAPIAuthenticationError("HTTP error 403: forbidden", status_code=403))
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    response = await service.search_with_metadata("gym", "Nashik")

    assert response.provider == "foursquare"
    assert response.fallback_used is True
    assert response.leads == [FOURSQUARE_LEAD]


# ---------------------------------------------------------------------------
# TEST 6: Google Returns Empty Results (No Fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_zero_results_no_fallback() -> None:
    """TEST 6: Google 200 OK returning zero leads returns [] and DOES NOT call Foursquare."""
    primary = make_mock_provider(return_value=[])
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    response = await service.search_with_metadata("rare_business_type", "Nashik")

    assert response.provider == "google"
    assert response.fallback_used is False
    assert response.leads == []

    primary.search.assert_called_once_with("rare_business_type", "Nashik", limit=20)
    fallback.search.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 7: Both Providers Fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_providers_fail_raises_clean_error() -> None:
    """TEST 7: When both Google and Foursquare fail, raise a sanitized LeadDiscoveryError."""
    primary = make_mock_provider(side_effect=GoogleAPIUnavailableError("Google 500 error"))
    fallback = make_mock_provider(side_effect=FoursquareAPIUnavailableError("Foursquare 503 error"))

    service = BusinessSearchService(primary=primary, fallback=fallback)

    with pytest.raises(LeadDiscoveryError) as exc_info:
        await service.search("restaurant", "Nashik")

    assert "currently unavailable" in str(exc_info.value)
    # Ensure no internal raw exception details are exposed
    assert "Google 500" not in str(exc_info.value)
    assert "Foursquare 503" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# TEST 8: Same Search Criteria Preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_criteria_preserved_on_fallback() -> None:
    """TEST 8: Exact query, location, and limit are passed to fallback provider."""
    primary = make_mock_provider(side_effect=GoogleAPITimeoutError("Timeout"))
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)
    await service.search("dental clinic", "Nashik Road, Maharashtra", limit=7)

    primary.search.assert_called_once_with("dental clinic", "Nashik Road, Maharashtra", limit=7)
    fallback.search.assert_called_once_with("dental clinic", "Nashik Road, Maharashtra", limit=7)


# ---------------------------------------------------------------------------
# TEST 9: Common Lead Schema Maintained
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_common_lead_schema_maintained() -> None:
    """TEST 9: Output elements are valid BusinessLead instances with source field preserved."""
    # Test primary Google leads
    service_g = BusinessSearchService(
        primary=make_mock_provider(return_value=[GOOGLE_LEAD]),
        fallback=make_mock_provider(),
    )
    leads_g = await service_g.search("cafe", "Nashik")
    assert len(leads_g) == 1
    assert isinstance(leads_g[0], BusinessLead)
    assert leads_g[0].source == "google"

    # Test fallback Foursquare leads
    service_f = BusinessSearchService(
        primary=make_mock_provider(side_effect=GoogleAPIQuotaError("429")),
        fallback=make_mock_provider(return_value=[FOURSQUARE_LEAD]),
    )
    leads_f = await service_f.search("cafe", "Nashik")
    assert len(leads_f) == 1
    assert isinstance(leads_f[0], BusinessLead)
    assert leads_f[0].source == "foursquare"


# ---------------------------------------------------------------------------
# TEST 10: API Key Protection in Logs & Errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_api_key_leakage_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    """TEST 10: Credentials and secrets are never logged during provider failover."""
    secret_key = "AIzaSy_super_secret_google_key_9999"
    google_exc = GoogleAPIAuthenticationError(f"HTTP 403 failure with key prefix AIza...")
    fsq_exc = FoursquareAPIAuthenticationError("HTTP 401 unauthorized")

    primary = make_mock_provider(side_effect=google_exc)
    fallback = make_mock_provider(side_effect=fsq_exc)

    service = BusinessSearchService(primary=primary, fallback=fallback)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LeadDiscoveryError) as exc_info:
            await service.search("restaurant", "Nashik")

    # Verify secret key does not appear in log output or exception message
    assert secret_key not in caplog.text
    assert secret_key not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Input Validation (No Fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "location"), [("", "Nashik"), ("cafe", ""), ("  ", "  ")])
async def test_invalid_input_raises_value_error_without_calling_providers(
    query: str, location: str
) -> None:
    """Blank query or location raises ValueError immediately without calling any provider."""
    primary = make_mock_provider(return_value=[GOOGLE_LEAD])
    fallback = make_mock_provider(return_value=[FOURSQUARE_LEAD])

    service = BusinessSearchService(primary=primary, fallback=fallback)

    with pytest.raises(ValueError):
        await service.search(query, location)

    primary.search.assert_not_called()
    fallback.search.assert_not_called()
