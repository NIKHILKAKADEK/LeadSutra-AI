"""Business search service facade and failover orchestrator for LeadSutra lead discovery.

Implements automatic failover orchestration between the primary provider (Google Places)
and the fallback provider (Foursquare Places).
"""

from __future__ import annotations

import logging

from app.models.lead import BusinessLead, BusinessSearchResponse
from app.services.lead_discovery.base import BaseBusinessDiscoveryProvider
from app.services.lead_discovery.exceptions import LeadDiscoveryError
from app.services.lead_discovery.foursquare_places import FoursquarePlacesProvider
from app.services.lead_discovery.google_places import GooglePlacesProvider

logger = logging.getLogger(__name__)


class BusinessSearchService:
    """Orchestrator that executes lead search with automatic provider failover.

    - Google Places API = PRIMARY provider.
    - Foursquare Places API = FALLBACK provider.

    Behavior rules:
    1. Always calls Google Places API first.
    2. If Google succeeds (including returning zero matching leads), returns Google results directly.
    3. If Google fails with a provider-level error (timeout, quota 429, 5xx, auth 401/403, malformed JSON),
       automatically attempts Foursquare Places API with identical parameters.
    4. If both providers fail, raises a sanitized ``LeadDiscoveryError`` without exposing credentials
       or internal stack traces.

    Parameters
    ----------
    primary:
        Primary discovery provider. Defaults to ``GooglePlacesProvider``.
    fallback:
        Fallback discovery provider. Defaults to ``FoursquarePlacesProvider``.
    """

    def __init__(
        self,
        primary: BaseBusinessDiscoveryProvider | None = None,
        fallback: BaseBusinessDiscoveryProvider | None = None,
    ) -> None:
        self._primary: BaseBusinessDiscoveryProvider = primary or GooglePlacesProvider()
        self._fallback: BaseBusinessDiscoveryProvider = fallback or FoursquarePlacesProvider()

    async def search(
        self,
        query: str,
        location: str,
        limit: int | None = 20,
    ) -> list[BusinessLead]:
        """Search for business leads, returning a simple list of normalised BusinessLead objects.

        Delegates to ``search_with_metadata`` and returns ``response.leads``.
        """
        response = await self.search_with_metadata(query, location, limit=limit)
        return response.leads

    async def search_with_metadata(
        self,
        query: str,
        location: str,
        limit: int | None = 20,
    ) -> BusinessSearchResponse:
        """Search for business leads, returning results along with provider failover metadata.

        Parameters
        ----------
        query:
            Business type or keyword (e.g. ``"restaurant"``).
        location:
            City / region string (e.g. ``"Nashik, Maharashtra"``).
        limit:
            Maximum number of results to return.

        Returns
        -------
        BusinessSearchResponse
            Container containing ``provider`` name, ``fallback_used`` flag, and list of ``leads``.

        Raises
        ------
        ValueError
            If *query* or *location* are blank (application input validation error, no fallback).
        LeadDiscoveryError
            If both primary and fallback discovery providers fail.
        """
        query = (query or "").strip()
        location = (location or "").strip()

        if not query:
            raise ValueError("'query' must be a non-empty string.")
        if not location:
            raise ValueError("'location' must be a non-empty string.")

        logger.info(
            "BusinessSearchService: Starting business search query=%r location=%r (limit=%s).",
            query,
            location,
            limit,
        )

        # ------------------------------------------------------------------
        # Step 1: Attempt Primary Provider (Google Places)
        # ------------------------------------------------------------------
        logger.info("BusinessSearchService: Trying Google Places provider (PRIMARY)...")
        try:
            results = await self._primary.search(query, location, limit=limit)
            logger.info(
                "BusinessSearchService: Google Places provider (PRIMARY) succeeded with %d lead(s).",
                len(results),
            )
            return BusinessSearchResponse(
                provider="google",
                fallback_used=False,
                leads=results,
            )
        except LeadDiscoveryError as primary_exc:
            logger.warning(
                "BusinessSearchService: Primary provider (Google Places) failed: %s. Initiating automatic fallback to Foursquare Places (FALLBACK)...",
                primary_exc.message,
            )

        # ------------------------------------------------------------------
        # Step 2: Attempt Fallback Provider (Foursquare Places)
        # ------------------------------------------------------------------
        logger.info("BusinessSearchService: Trying Foursquare Places provider (FALLBACK)...")
        try:
            fallback_results = await self._fallback.search(query, location, limit=limit)
            logger.info(
                "BusinessSearchService: Fallback provider (Foursquare Places) succeeded with %d lead(s).",
                len(fallback_results),
            )
            return BusinessSearchResponse(
                provider="foursquare",
                fallback_used=True,
                leads=fallback_results,
            )
        except LeadDiscoveryError as fallback_exc:
            logger.error(
                "BusinessSearchService: Both primary (Google) and fallback (Foursquare) providers failed. Fallback error: %s",
                fallback_exc.message,
            )

        # ------------------------------------------------------------------
        # Step 3: Dual Failure State
        # ------------------------------------------------------------------
        raise LeadDiscoveryError(
            "Business discovery services are currently unavailable. Please try again later."
        )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_service: BusinessSearchService | None = None


def _get_default_service() -> BusinessSearchService:
    """Return or instantiate the default global ``BusinessSearchService``."""
    global _default_service  # noqa: PLW0603
    if _default_service is None:
        _default_service = BusinessSearchService()
    return _default_service


async def search_businesses(
    query: str,
    location: str,
    limit: int | None = 20,
) -> list[BusinessLead]:
    """Search for businesses using the default ``BusinessSearchService`` with automatic failover."""
    service = _get_default_service()
    return await service.search(query, location, limit=limit)


async def search_businesses_with_metadata(
    query: str,
    location: str,
    limit: int | None = 20,
) -> BusinessSearchResponse:
    """Search for businesses returning provider failover metadata using the default service."""
    service = _get_default_service()
    return await service.search_with_metadata(query, location, limit=limit)


async def search_and_enrich_leads(
    query: str,
    location: str,
    limit: int | None = 20,
    deduplicate: bool = True,
    enrich_websites: bool = True,
    extract_contacts: bool = True,
    score_leads: bool = True,
) -> list[BusinessLead]:
    """Execute complete LeadSutra discovery & enrichment pipeline:
    Search (Google -> Foursquare failover) -> Deduplication -> Website Enrichment -> Contact Extraction -> Lead Scoring.
    """
    leads = await search_businesses(query, location, limit=limit)
    if deduplicate:
        from app.services.lead_discovery.deduplication import deduplicate_leads

        leads = deduplicate_leads(leads)
    if enrich_websites:
        from app.services.website_scraping.enrichment_service import enrich_leads

        leads = await enrich_leads(leads)
    if extract_contacts:
        from app.services.contact_extraction.extractor_service import extract_leads_contact_info

        leads = await extract_leads_contact_info(leads)
    if score_leads:
        from app.services.lead_scoring.scoring_service import score_leads as score_leads_fn

        leads, _ = score_leads_fn(leads, target_category=query)
    return leads


async def search_and_extract_business_profiles(
    query: str,
    location: str,
    limit: int | None = 20,
    deduplicate: bool = True,
    enrich_websites: bool = True,
    extract_contacts: bool = True,
):
    """Execute complete LeadSutra pipeline returning both BusinessLead objects and linked BusinessProfile models."""
    leads = await search_and_enrich_leads(
        query,
        location,
        limit=limit,
        deduplicate=deduplicate,
        enrich_websites=enrich_websites,
        extract_contacts=extract_contacts,
        score_leads=True,
    )
    from app.services.business_info_extraction.profile_extractor_service import extract_business_profiles

    return await extract_business_profiles(leads)


async def search_enrich_score_and_persist_leads(
    query: str,
    location: str,
    limit: int | None = 20,
    deduplicate: bool = True,
    enrich_websites: bool = True,
    extract_contacts: bool = True,
    score_leads: bool = True,
):
    """Execute complete LeadSutra pipeline and persist output BusinessLead & BusinessProfile models in MongoDB.
    Search -> Deduplication -> Website Scraping -> Contact Extraction -> Profile Extraction -> Lead Scoring -> MongoDB.
    """
    leads, profiles = await search_and_extract_business_profiles(
        query,
        location,
        limit=limit,
        deduplicate=deduplicate,
        enrich_websites=enrich_websites,
        extract_contacts=extract_contacts,
    )

    from app.db.repositories.lead_repository import default_lead_repository

    persisted_leads = []
    persisted_profiles = []

    for lead in leads:
        saved_lead = await default_lead_repository.save_or_merge_lead(lead)
        persisted_leads.append(saved_lead)

    for profile in profiles:
        saved_prof = await default_lead_repository.save_business_profile(profile)
        persisted_profiles.append(saved_prof)

    return persisted_leads, persisted_profiles





