"""Google Places API (New) business discovery provider for LeadSutra."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from dotenv import find_dotenv, load_dotenv

from app.models.lead import BusinessLead
from app.services.lead_discovery.base import BaseBusinessDiscoveryProvider
from app.services.lead_discovery.exceptions import (
    GoogleAPIAuthenticationError,
    GoogleAPIMalformedResponseError,
    GoogleAPIQuotaError,
    GoogleAPITimeoutError,
    GoogleAPIUnavailableError,
    GooglePlacesAPIError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Request only the fields LeadSutra needs; avoids over-fetching and extra cost.
FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.primaryType,"
    "places.rating,"
    "places.userRatingCount,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.location"
)

_DEFAULT_TIMEOUT_SECONDS = 10.0
_DEFAULT_MINIMUM_RATING = 0.0


def _mask_key(api_key: str) -> str:
    """Return a safe, partially masked representation of an API key for logging."""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}"


class GooglePlacesProvider(BaseBusinessDiscoveryProvider):
    """Business discovery provider backed by Google Places API (New).

    Uses the Text Search endpoint with a fixed field mask to keep
    requests cheap and responses consistent.

    Parameters
    ----------
    api_key:
        Google Maps / Places API key.  When omitted the value is loaded
        from the ``GOOGLE_MAPS_API_KEY`` (or ``GOOGLE_PLACES_API_KEY``)
        environment variable (dotenv is loaded automatically).
    minimum_rating:
        Leads with a Google rating below this threshold are discarded.
        Defaults to ``0.0`` (all leads returned).
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        minimum_rating: float = _DEFAULT_MINIMUM_RATING,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        load_dotenv(find_dotenv(usecwd=True), override=True)
        self._api_key: str = api_key or os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY") or ""
        self._minimum_rating = minimum_rating
        self._timeout = timeout

        if self._api_key:
            logger.debug("GooglePlacesProvider initialised with key %s", _mask_key(self._api_key))
        else:
            logger.warning("GooglePlacesProvider: no API key configured.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        location: str,
        limit: int | None = 20,
    ) -> list[BusinessLead]:
        """Search Google Places for businesses matching *query* near *location*.

        Parameters
        ----------
        query:
            Business type or keyword (e.g. ``"cafe"``).
        location:
            City / region string (e.g. ``"Nashik, Maharashtra"``).
        limit:
            Maximum number of results to return (capped to 20 by the
            Google Places Text Search endpoint).

        Returns
        -------
        list[BusinessLead]
            Normalised leads filtered by *minimum_rating*.

        Raises
        ------
        GoogleAPIAuthenticationError
            On HTTP 401 / 403.
        GoogleAPIQuotaError
            On HTTP 429.
        GoogleAPIUnavailableError
            On HTTP 5xx.
        GoogleAPITimeoutError
            When the request times out.
        GoogleAPIMalformedResponseError
            When the response cannot be parsed.
        GooglePlacesAPIError
            For any other Google Places error.
        """
        if not query or not query.strip():
            raise ValueError("'query' must not be empty.")
        if not location or not location.strip():
            raise ValueError("'location' must not be empty.")

        text_query = f"{query.strip()} in {location.strip()}"
        payload: dict[str, Any] = {"textQuery": text_query}
        if limit is not None:
            payload["pageSize"] = min(limit, 20)

        active_key = self._api_key or os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY") or ""
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": active_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

        logger.debug("GooglePlacesProvider: POST %s query=%r", PLACES_TEXT_SEARCH_URL, text_query)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    PLACES_TEXT_SEARCH_URL,
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise GoogleAPITimeoutError(f"Request to Google Places timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GooglePlacesAPIError(f"HTTP transport error: {exc}") from exc

        self._raise_for_status(response)

        try:
            data = response.json()
            places = data.get("places") or []
        except Exception as exc:
            raise GoogleAPIMalformedResponseError(
                f"Could not parse Google Places response: {exc}"
            ) from exc

        leads: list[BusinessLead] = []
        for place in places:
            lead = self._map_place(place)
            if lead.rating is None or lead.rating >= self._minimum_rating:
                leads.append(lead)

        logger.debug(
            "GooglePlacesProvider: %d result(s) returned (%d after rating filter).",
            len(places),
            len(leads),
        )
        return leads

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP error status codes to typed LeadSutra exceptions."""
        status = response.status_code
        if status < 400:
            return

        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message") if isinstance(err_data, dict) else str(err_data)
            err_msg = err_msg or response.text[:200]
        except Exception:
            err_msg = response.text[:200]

        if status in (401, 403):
            raise GoogleAPIAuthenticationError(
                f"HTTP error {status}: {err_msg}",
                status_code=status,
            )
        if status == 429:
            raise GoogleAPIQuotaError(
                f"HTTP error {status}: {err_msg}",
                status_code=status,
            )
        if status >= 500:
            raise GoogleAPIUnavailableError(
                f"HTTP error {status}: {err_msg}",
                status_code=status,
            )
        # 4xx catch-all
        raise GooglePlacesAPIError(
            f"HTTP error {status}: {err_msg}",
            status_code=status,
        )

    @staticmethod
    def _map_place(place: dict[str, Any]) -> BusinessLead:
        """Convert a raw Google Places place dict to a ``BusinessLead``."""
        location = place.get("location") or {}
        display_name = place.get("displayName") or {}

        return BusinessLead(
            external_place_id=place.get("id"),
            source="google",
            name=(display_name.get("text") or "").strip() or "Unknown",
            category=place.get("primaryType"),
            rating=place.get("rating"),
            phone=place.get("nationalPhoneNumber"),
            website=place.get("websiteUri"),
            address=place.get("formattedAddress"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
        )
