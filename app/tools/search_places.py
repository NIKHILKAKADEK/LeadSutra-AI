"""Lead discovery tool wrapping Google Places API and Google Maps browser discovery."""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import DiscoverySettings
from app.integrations.google_places import GooglePlacesClient, PlacesApiError
from app.integrations.maps_scraper import GoogleMapsBrowserDiscovery
from app.agents.lead_pipeline.schemas import BusinessRecord, PlacesConfig

logger = logging.getLogger(__name__)


async def search_places(
    query: str,
    location: str,
    limit: int = 10,
    *,
    settings: DiscoverySettings | None = None,
) -> list[BusinessRecord]:
    """Search for business places using Google Places API with Maps browser fallback.

    Args:
        query: Business category or search phrase.
        location: Target city or geographic region.
        limit: Maximum number of businesses to return.
        settings: Optional custom DiscoverySettings.
    """
    settings = settings or DiscoverySettings()
    client = GooglePlacesClient(config=PlacesConfig.from_env(settings))

    if settings.leadsutra_enable_google_places:
        try:
            places = await client.search_text(query=query, location=location, limit=limit)
            if places or not settings.leadsutra_maps_fallback_on_zero_results:
                return places
            logger.info("Google Places returned 0 results; fallback enabled.")
        except Exception as exc:
            if not settings.leadsutra_enable_maps_browser_fallback:
                raise
            logger.warning("Google Places search failed (%s); trying browser scraper fallback.", exc)

    if settings.leadsutra_enable_maps_browser:
        browser = GoogleMapsBrowserDiscovery()
        return await browser.search(query=query, location=location, limit=limit)

    return []
