"""Backwards-compatibility shim for app.agents.lead_discovery.maps_search.

The original prototype used this module directly.  All new code should
import from ``app.services.lead_discovery`` instead.

This shim:
- Re-exports ``search_businesses`` from the service layer.
- Re-exports ``httpx`` so existing tests can monkeypatch it here.
- Exposes ``BusinessSearchResult`` as an alias for ``BusinessLead``.
- Exposes ``MapsAPIError`` as an alias for ``GooglePlacesAPIError``.
- Re-exports the URL and field-mask constants.
"""

from __future__ import annotations

import httpx  # noqa: F401  – tests monkeypatch `maps_search.httpx`

from app.models.lead import BusinessLead
from app.services.lead_discovery.exceptions import (
    GoogleAPIAuthenticationError,
    GoogleAPIMalformedResponseError,
    GoogleAPIQuotaError,
    GoogleAPITimeoutError,
    GoogleAPIUnavailableError,
    GooglePlacesAPIError,
    LeadDiscoveryError,
)
from app.services.lead_discovery.google_places import (
    FIELD_MASK,
    PLACES_TEXT_SEARCH_URL,
    GooglePlacesProvider,
)
from app.services.lead_discovery.search_service import search_businesses  # noqa: F401

# ---------------------------------------------------------------------------
# Legacy aliases
# ---------------------------------------------------------------------------

#: Alias kept for backwards compatibility with existing tests/code.
BusinessSearchResult = BusinessLead

#: Alias kept for backwards compatibility with existing tests/code.
MapsAPIError = GooglePlacesAPIError

__all__ = [
    "BusinessSearchResult",
    "FIELD_MASK",
    "GoogleAPIAuthenticationError",
    "GoogleAPIMalformedResponseError",
    "GoogleAPIQuotaError",
    "GoogleAPITimeoutError",
    "GoogleAPIUnavailableError",
    "GooglePlacesAPIError",
    "GooglePlacesProvider",
    "LeadDiscoveryError",
    "MapsAPIError",
    "PLACES_TEXT_SEARCH_URL",
    "httpx",
    "search_businesses",
]
