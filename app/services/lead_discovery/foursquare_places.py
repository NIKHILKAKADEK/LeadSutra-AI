"""Foursquare Places API business discovery provider for LeadSutra."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from dotenv import find_dotenv, load_dotenv

from app.models.lead import BusinessLead
from app.services.lead_discovery.base import BaseBusinessDiscoveryProvider
from app.services.lead_discovery.exceptions import (
    FoursquareAPIAuthenticationError,
    FoursquareAPIMalformedResponseError,
    FoursquareAPIQuotaError,
    FoursquareAPITimeoutError,
    FoursquareAPIUnavailableError,
    FoursquarePlacesAPIError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FOURSQUARE_SEARCH_URL = "https://places-api.foursquare.com/places/search"

# Standard requested fields from Foursquare Places API
FOURSQUARE_FIELDS = (
    # "fsq_place_id,"
    "name,"
    # "rating,"
    "email,"
    "tel,"
    "website,"
    "location,"
    "categories,"
)

_DEFAULT_TIMEOUT_SECONDS = 10.0
_DEFAULT_MINIMUM_RATING = 0.0


def _mask_key(api_key: str) -> str:
    """Return a safe, partially masked representation of an API key for logging."""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}"


class FoursquarePlacesProvider(BaseBusinessDiscoveryProvider):
    """Business discovery provider backed by the Foursquare Places API.

    Functions as an independent discovery provider or secondary fallback provider
    in LeadSutra's multi-agent sales architecture.

    Parameters
    ----------
    api_key:
        Foursquare API key / Bearer token. When omitted, loaded from the
        ``FOURSQUARE_API_KEY`` environment variable.
    minimum_rating:
        Leads with a normalized rating (0.0 - 5.0 scale) below this threshold
        are filtered out. Defaults to ``0.0``.
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
        self._api_key: str = api_key or os.getenv("FOURSQUARE_API_KEY") or ""
        self._minimum_rating = minimum_rating
        self._timeout = timeout

        if self._api_key:
            logger.debug("FoursquarePlacesProvider initialised with key %s", _mask_key(self._api_key))
        else:
            logger.warning("FoursquarePlacesProvider: no API key configured.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        location: str,
        limit: int | None = 20,
    ) -> list[BusinessLead]:
        """Search Foursquare Places for businesses matching *query* near *location*.

        Parameters
        ----------
        query:
            Business category or keyword (e.g. ``"restaurant"``).
        location:
            City / region string (e.g. ``"Nashik, Maharashtra"``).
        limit:
            Maximum number of results to return (capped to 50 by Foursquare API).

        Returns
        -------
        list[BusinessLead]
            Normalised leads filtered by *minimum_rating*.

        Raises
        ------
        ValueError
            If *query* or *location* are blank.
        FoursquareAPIAuthenticationError
            On HTTP 401 / 403.
        FoursquareAPIQuotaError
            On HTTP 429.
        FoursquareAPIUnavailableError
            On HTTP 5xx.
        FoursquareAPITimeoutError
            When the request times out.
        FoursquareAPIMalformedResponseError
            When the response cannot be parsed.
        FoursquarePlacesAPIError
            For any other Foursquare API error.
        """
        if not query or not query.strip():
            raise ValueError("'query' must not be empty.")
        if not location or not location.strip():
            raise ValueError("'location' must not be empty.")

        active_key = self._api_key or os.getenv("FOURSQUARE_API_KEY") or ""
        if not active_key or not active_key.strip():
            raise FoursquareAPIAuthenticationError("Foursquare API key is missing or not configured.", status_code=401)

        params: dict[str, Any] = {
            "query": query.strip(),
            "near": location.strip(),
            "fields": FOURSQUARE_FIELDS,
        }
        if limit is not None:
            params["limit"] = min(limit, 50)

        headers = {
            "Authorization": f"Bearer {active_key}",
            "X-Places-Api-Version": "2025-06-17",
            "Accept": "application/json",
        }

        logger.debug(
            "FoursquarePlacesProvider: GET %s query=%r near=%r",
            FOURSQUARE_SEARCH_URL,
            query.strip(),
            location.strip(),
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    FOURSQUARE_SEARCH_URL,
                    params=params,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise FoursquareAPITimeoutError(f"Request to Foursquare Places timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise FoursquarePlacesAPIError(f"HTTP transport error: {exc}") from exc

        self._raise_for_status(response)

        try:
            data = response.json()
            results = data.get("results")
            if results is None:
                raise ValueError("Missing 'results' key in JSON response.")
        except Exception as exc:
            raise FoursquareAPIMalformedResponseError(
                f"Could not parse Foursquare Places response: {exc}"
            ) from exc

        leads: list[BusinessLead] = []
        for place in results:
            lead = self._map_place(place, default_category=query.strip())
            # Minimum rating check on normalized 0-5 rating
            if lead.rating is None or lead.rating >= self._minimum_rating:
                leads.append(lead)

        logger.debug(
            "FoursquarePlacesProvider: %d result(s) returned (%d after rating filter).",
            len(results),
            len(leads),
        )
        return leads

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP error status codes to typed Foursquare exception classes."""
        status = response.status_code
        if status < 400:
            return

        try:
            data = response.json()
            err_msg = data.get("message") or data.get("error") or response.text[:200]
        except Exception:
            err_msg = response.text[:200]

        if status in (401, 403):
            raise FoursquareAPIAuthenticationError(
                f"HTTP error {status}: {err_msg}",
                status_code=status,
            )
        if status == 429:
            raise FoursquareAPIQuotaError(
                f"HTTP error {status}: {err_msg}",
                status_code=status,
            )
        if status >= 500:
            raise FoursquareAPIUnavailableError(
                f"HTTP error {status}: {err_msg}",
                status_code=status,
            )
        # 4xx catch-all
        raise FoursquarePlacesAPIError(
            f"HTTP error {status}: {err_msg}",
            status_code=status,
        )

    @staticmethod
    def _map_place(place: dict[str, Any], default_category: str) -> BusinessLead:
        """Convert a raw Foursquare place dict to a normalised ``BusinessLead``.

        - Foursquare rating (0–10) is converted to standard 0–5 scale:
            ``rating_5 = round(rating_10 / 2, 1)``
        - First category in categories list is extracted.
        """
        location = place.get("location") or {}
        geocodes = place.get("geocodes") or {}
        main_geocode = geocodes.get("main") or geocodes.get("roof") or {}

        # Rating conversion: 0–10 -> 0–5
        raw_rating = place.get("rating")
        rating_5: float | None = None
        if raw_rating is not None and isinstance(raw_rating, (int, float)):
            rating_5 = round(float(raw_rating) / 2.0, 1)

        # Primary category extraction
        categories = place.get("categories") or []
        category_name: str | None = default_category
        if categories and isinstance(categories, list) and isinstance(categories[0], dict):
            cat_name = categories[0].get("name")
            if cat_name:
                category_name = cat_name

        # Geocode coordinates fallback
        lat = main_geocode.get("latitude") or location.get("latitude")
        lng = main_geocode.get("longitude") or location.get("longitude")

        return BusinessLead(
            external_place_id=place.get("fsq_place_id"),
            source="foursquare",
            name=(place.get("name") or "").strip() or "Unknown",
            category=category_name,
            rating=rating_5,
            phone=place.get("tel"),
            email=place.get("email"),
            website=place.get("website"),
            address=location.get("formatted_address"),
            latitude=lat,
            longitude=lng,
        )
