"""Exceptions for LeadSutra discovery services."""

from __future__ import annotations


class LeadDiscoveryError(Exception):
    """Base exception for all lead discovery operations in LeadSutra."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GooglePlacesAPIError(LeadDiscoveryError):
    """Base exception for Google Places API errors."""

    pass


class GoogleAPIAuthenticationError(GooglePlacesAPIError):
    """Raised when Google Places API authentication or authorization fails (HTTP 401/403)."""

    pass


class GoogleAPIQuotaError(GooglePlacesAPIError):
    """Raised when Google Places API quota or rate limit is exceeded (HTTP 429)."""

    pass


class GoogleAPIUnavailableError(GooglePlacesAPIError):
    """Raised when Google Places API returns server errors or is unavailable (HTTP 5xx)."""

    pass


class GoogleAPITimeoutError(GooglePlacesAPIError):
    """Raised when a request to Google Places API times out."""

    pass


class GoogleAPIMalformedResponseError(GooglePlacesAPIError):
    """Raised when Google Places API returns unexpected or malformed response data."""

    pass


# ---------------------------------------------------------------------------
# Foursquare Places API Exception Hierarchy
# ---------------------------------------------------------------------------


class FoursquarePlacesAPIError(LeadDiscoveryError):
    """Base exception for Foursquare Places API errors."""

    pass


class FoursquareAPIAuthenticationError(FoursquarePlacesAPIError):
    """Raised when Foursquare API authentication or authorization fails (HTTP 401/403)."""

    pass


class FoursquareAPIQuotaError(FoursquarePlacesAPIError):
    """Raised when Foursquare API quota or rate limit is exceeded (HTTP 429)."""

    pass


class FoursquareAPIUnavailableError(FoursquarePlacesAPIError):
    """Raised when Foursquare API returns server errors or is unavailable (HTTP 5xx)."""

    pass


class FoursquareAPITimeoutError(FoursquarePlacesAPIError):
    """Raised when a request to Foursquare API times out."""

    pass


class FoursquareAPIMalformedResponseError(FoursquarePlacesAPIError):
    """Raised when Foursquare API returns unexpected or malformed response data."""

    pass

