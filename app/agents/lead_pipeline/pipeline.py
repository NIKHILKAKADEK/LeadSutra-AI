"""Discovery and enrichment pipeline; scoring and contracts live alongside it."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Iterable
from functools import partial
from time import perf_counter
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

from app.core.config import DiscoverySettings
from app.integrations.google_places import (
    GooglePlacesClient, PlacesApiError, PlacesConfigurationError, PLACES_MAX_RESULTS_PER_QUERY,
)
from app.integrations.maps_scraper import GoogleMapsBrowserDiscovery
from app.integrations.website_fetcher import WebsiteCrawler
from app.services.lead_results import LeadResultStore
from .scoring import score_lead, select_leads, validate_selection
from .schemas import (
    BusinessRecord, BusinessProfile, ProfileFact, OperatingHours,
    WebsitePage, WebsiteCrawlResult, WebsiteCrawlerConfig, WebsiteStatus,
    ContactValue, ContactEmail, ContactPhone, ContactExtraction,
    SocialAccount, SocialMediaExtraction, DetectedTechnology,
    TechnologyExtraction, ScoringConfig,
    LeadResult, LeadDiscoveryRunResult, PlacesConfig,
)

logger = logging.getLogger(__name__)


class LeadPipeline:
    """Public entry point: run discovery, enrichment, scoring and final persistence."""

    def __init__(
        self, *, places_client: GooglePlacesClient | None = None,
        browser_discovery: GoogleMapsBrowserDiscovery | None = None,
        crawler: WebsiteCrawler | None = None,
        crawler_config: WebsiteCrawlerConfig | None = None,
        scoring_config: ScoringConfig | None = None,
        scorer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        result_store: LeadResultStore | None = None,
        discovery_settings: DiscoverySettings | None = None,
    ) -> None:
        settings = discovery_settings if discovery_settings is not None else DiscoverySettings()
        self.places_client = places_client or GooglePlacesClient(config=PlacesConfig.from_env(settings))
        self.browser_discovery = browser_discovery or GoogleMapsBrowserDiscovery()
        self.crawler = crawler or WebsiteCrawler(config=crawler_config)
        self.scorer = scorer or partial(score_lead, config=scoring_config or ScoringConfig())
        self.result_store = result_store if result_store is not None else LeadResultStore()
        self.google_places_enabled = settings.leadsutra_enable_google_places
        self.maps_browser_enabled = settings.leadsutra_enable_maps_browser
        self.allow_browser_fallback = settings.leadsutra_enable_maps_browser_fallback
        self.fallback_on_zero_results = settings.leadsutra_maps_fallback_on_zero_results
        self.diagnostics: dict[str, Any] = {}

    async def run(
        self, query: str, location: str, limit: int = 10,
        mode: str = "full", qualification: str = "mixed", priority: str | None = None,
    ) -> LeadDiscoveryRunResult:
        """Return the final filtered leads and persist the existing canonical output.

        Mode and qualification remain internal/legacy options; the v1 request
        contract still accepts only query, location, limit and priority.
        """
        validate_selection(limit, mode, qualification, priority)
        candidate_limit = limit
        if mode in ("full", "scoring"):
            candidate_limit = min(
                max(limit * 5, limit + 20), max(PLACES_MAX_RESULTS_PER_QUERY, limit),
            )
        logger.info(
            "Executing lead discovery pipeline: query=%s, location=%s, limit=%d, mode=%s",
            query, location, limit, mode,
        )
        started = perf_counter()
        discovered = await self._discover(query=query, location=location, limit=candidate_limit)
        diagnostics = dict(self.diagnostics)
        source = diagnostics.get("source", "google_places")
        fallback_used = diagnostics.get("fallback_used", False)
        fallback_reason = diagnostics.get("fallback_reason")
        timings = {"discovery": perf_counter() - started, "enrichment": 0.0, "scoring": 0.0}
        for stage in ("places", "maps_fallback", "normalization_deduplication"):
            if f"{stage}_seconds" in diagnostics:
                timings[stage] = diagnostics[f"{stage}_seconds"]

        if mode == "basic":
            candidates = [{
                "lead_id": business.lead_id,
                "business": business.model_dump(mode="json"),
                "profile": {}, "website_analysis": {}, "contacts": {},
                "social_links": {}, "lead_scoring": {},
            } for business in discovered]
        else:
            config = getattr(self.crawler, "config", None)
            semaphore = asyncio.Semaphore(getattr(config, "concurrency", 1))

            async def enrich(business: BusinessRecord) -> dict[str, Any]:
                async with semaphore:
                    lead = await self._enrich(business)
                    if mode in ("full", "scoring"):
                        scoring_started = perf_counter()
                        lead["lead_scoring"] = self.scorer(lead)
                        timings["scoring"] += perf_counter() - scoring_started
                    return lead

            enrichment_started = perf_counter()
            tasks = [asyncio.create_task(enrich(business)) for business in discovered]
            try:
                candidates = await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            timings["enrichment"] = perf_counter() - enrichment_started - timings["scoring"]

        qualification_started = perf_counter()
        final_leads, selection = select_leads(candidates, limit, qualification, priority)
        timings["qualification_selection"] = perf_counter() - qualification_started
        diagnostics.update(selection)
        diagnostics.update(candidate_limit=candidate_limit, candidates_discovered=len(discovered))
        try:
            serialization_started = perf_counter()
            canonical_leads = [canonical_lead_output(lead) for lead in final_leads]
            timings["serialization"] = perf_counter() - serialization_started
            persistence_started = perf_counter()
            result_path = await asyncio.to_thread(self.result_store.save, canonical_leads)
            timings["persistence"] = perf_counter() - persistence_started
        except Exception as exc:
            raise RuntimeError("Failed to persist final lead results.") from exc

        timings["total"] = perf_counter() - started
        diagnostics["timings_seconds"] = timings
        logger.info(
            "Lead pipeline completed: discovered=%d selection=%s source=%s "
            "fallback_used=%s result_path=%s timings_seconds=%s",
            len(discovered), selection, source, fallback_used, result_path, timings,
        )
        return LeadDiscoveryRunResult(
            leads=final_leads, source=source, fallback_used=fallback_used,
            fallback_reason=fallback_reason, diagnostics=diagnostics, result_path=result_path,
        )


    async def _discover(
        self,
        query: str,
        location: str,
        limit: int = 50,
    ) -> list[BusinessRecord]:
        """
        Discover businesses.
        Args:
            query:
                Business category/search query.
            location:
                Geographic location.
            limit:
                Maximum number of businesses to return.
        Returns:
            Deduplicated BusinessRecord objects.
        """
        query = query.strip()
        location = location.strip()
        if not query:
            raise ValueError("query is required")
        if not location:
            raise ValueError("location is required")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._reset_diagnostics(limit)
        if not self.google_places_enabled:
            if not self.maps_browser_enabled:
                raise PlacesConfigurationError(
                    "All discovery providers are disabled; enable Google Places or Maps browser in .env."
                )
            return await self._browser_fallback(
                query=query, location=location, limit=limit, reason="google_places_disabled",
            )
        # --------------------------------------------------------------
        # PRIMARY PROVIDER
        # --------------------------------------------------------------
        places_started = perf_counter()
        try:
            records = await self.places_client.search(
                query=query,
                location=location,
                limit=limit,
            )
        except PlacesConfigurationError as exc:
            self.diagnostics["places_seconds"] = perf_counter() - places_started
            return await self._handle_configuration_failure(
                query=query,
                location=location,
                limit=limit,
                error=exc,
            )
        except PlacesApiError as exc:
            self.diagnostics["places_seconds"] = perf_counter() - places_started
            return await self._handle_api_failure(
                query=query,
                location=location,
                limit=limit,
                error=exc,
            )
        # --------------------------------------------------------------
        # PRIMARY PROVIDER SUCCEEDED
        # --------------------------------------------------------------
        self.diagnostics["places_seconds"] = perf_counter() - places_started
        records = self._deduplicate_records(records)
        self.diagnostics["result_count"] = len(records)
        self.diagnostics["limit_capped_by_provider"] = (
            limit > PLACES_MAX_RESULTS_PER_QUERY
            and len(records) >= PLACES_MAX_RESULTS_PER_QUERY
        )
        # --------------------------------------------------------------
        # OPTIONAL ZERO-RESULT FALLBACK
        # --------------------------------------------------------------
        if (
            not records
            and self.maps_browser_enabled
            and self.allow_browser_fallback
            and self.fallback_on_zero_results
        ):
            return await self._browser_fallback(
                query=query,
                location=location,
                limit=limit,
                reason="places_api_zero_results",
            )
        return records[:limit]

    async def _handle_configuration_failure(
        self,
        *,
        query: str,
        location: str,
        limit: int,
        error: PlacesConfigurationError,
    ) -> list[BusinessRecord]:
        message = str(error)
        self.diagnostics["error"] = message
        # Your existing scraper explicitly allows browser fallback
        # when the Places API key is missing.
        if self.maps_browser_enabled and "missing places api key" in message.casefold():
            self.diagnostics["original_api_failure"] = message
            return await self._browser_fallback(
                query=query,
                location=location,
                limit=limit,
                reason="missing_places_api_key",
            )
        raise error

    async def _handle_api_failure(
        self,
        *,
        query: str,
        location: str,
        limit: int,
        error: PlacesApiError,
    ) -> list[BusinessRecord]:
        self.diagnostics["original_api_failure"] = str(error)
        # --------------------------------------------------------------
        # PRESERVE PARTIAL RESULTS
        # --------------------------------------------------------------
        partial_records = list(
            getattr(
                self.places_client,
                "last_records",
                [],
            )
        )
        if partial_records:
            self.diagnostics["partial_results_preserved"] = True
            self.diagnostics["result_count"] = len(
                partial_records
            )
            return self._deduplicate_records(
                partial_records
            )[:limit]
        # --------------------------------------------------------------
        # FALLBACK ONLY IF ERROR IS RETRYABLE AND ENABLED
        # --------------------------------------------------------------
        if not (
            self.maps_browser_enabled
            and self.allow_browser_fallback
            and error.retryable
        ):
            raise error
        reason = (
            "transient_api_failure:"
            f"{error.status_code or error.api_status or type(error).__name__}"
        )
        return await self._browser_fallback(
            query=query,
            location=location,
            limit=limit,
            reason=reason,
        )

    async def _browser_fallback(
        self,
        *,
        query: str,
        location: str,
        limit: int,
        reason: str,
    ) -> list[BusinessRecord]:
        if not self.maps_browser_enabled:
            raise PlacesConfigurationError("Google Maps browser discovery is disabled in .env.")
        logger.warning(
            "Places discovery unavailable (%s); "
            "falling back to Google Maps browser.",
            reason,
        )
        self.diagnostics.update(
            {
                "source": "google_maps_browser",
                "fallback_attempted": True,
                "fallback_reason": reason,
            }
        )
        fallback_started = perf_counter()
        try:
            records = await self.browser_discovery.search(
                query=query,
                location=location,
                limit=limit,
            )
        except Exception as exc:
            detail = str(exc).strip()
            # Preserve the Windows/Playwright diagnostic behavior
            # from the original scraper.
            if isinstance(exc, NotImplementedError):
                loop_name = type(
                    asyncio.get_running_loop()
                ).__name__
                detail = (
                    detail
                    or
                    "Playwright could not start its browser driver "
                    f"(event loop: {loop_name})"
                )
                if os.name == "nt":
                    detail += (
                        "; on Windows run Uvicorn without --reload "
                        "so Playwright can use a subprocess-capable "
                        "event loop"
                    )
            self.diagnostics["fallback_error"] = (
                f"{type(exc).__name__}: {detail}"
            )
            raise
        finally:
            self.diagnostics["maps_fallback_seconds"] = perf_counter() - fallback_started
        # --------------------------------------------------------------
        # Mark fallback metadata
        # --------------------------------------------------------------
        normalized: list[BusinessRecord] = []
        for record in records:
            normalized.append(
                record.model_copy(
                    update={
                        "discovery_source": "google_maps_browser",
                        "fallback_used": True,
                        "fallback_reason": reason,
                    }
                )
            )
        normalized = self._deduplicate_records(
            normalized
        )
        self.diagnostics.update(
            {
                "source": "google_maps_browser",
                "fallback_used": True,
                "fallback_attempted": True,
                "fallback_reason": reason,
                "result_count": len(normalized),
            }
        )
        return normalized[:limit]

    def _reset_diagnostics(self, limit: int) -> None:
        self.diagnostics = {
            "source": "google_places",
            "fallback_used": False,
            "fallback_reason": None,
            "fallback_attempted": False,
            "google_places_enabled": self.google_places_enabled,
            "maps_browser_enabled": self.maps_browser_enabled,
            "fallback_enabled": self.maps_browser_enabled and self.allow_browser_fallback,
            "missing_key_fallback_enabled": self.maps_browser_enabled,
            "zero_result_fallback_enabled": (
                self.fallback_on_zero_results
            ),
            "provider_result_cap_per_query": (
                PLACES_MAX_RESULTS_PER_QUERY
            ),
            "requested_limit": limit,
            "original_api_failure": None,
        }

    async def _enrich(
        self,
        business: BusinessRecord,
    ) -> dict[str, Any]:
        """
        Enrich one discovered business.
        Returns a canonical dictionary containing:
        business
        profile
        website_analysis
        contacts
        social_links
        extraction_metadata
        """
        if not isinstance(business, BusinessRecord):
            business = BusinessRecord.model_validate(
                business
            )
        # --------------------------------------------------------------
        # WEBSITE CRAWL
        # --------------------------------------------------------------
        try:
            website = await self.crawler.crawl(
                business
            )
        except Exception as exc:
            logger.exception(
                "Website enrichment failed for lead %s",
                business.lead_id,
            )
            # Do not destroy the discovered lead just because
            # website enrichment failed.
            website = WebsiteCrawlResult(
                lead_id=business.lead_id,
                website_status=WebsiteStatus.UNCERTAIN,
                website_url=business.website,
            )
            website.crawl_errors.append(
                {
                    "url": business.website,
                    "message": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )
        # --------------------------------------------------------------
        # PROFILE EXTRACTION
        # --------------------------------------------------------------
        try:
            profile = build_business_profile(
                business,
                website,
            )
            profile_status = (
                "success"
                if (
                    profile.services
                    or profile.products
                    or profile.target_customers
                    or profile.about_info
                    or profile.business_description
                    or profile.operating_hours
                )
                else "partial"
            )
        except Exception as exc:
            logger.exception(
                "Profile extraction failed for lead %s",
                business.lead_id,
            )
            profile = BusinessProfile(
                lead_id=business.lead_id,
                business_name=business.business_name,
            )
            profile_status = "not_available"
        # --------------------------------------------------------------
        # CONTACT EXTRACTION
        # --------------------------------------------------------------
        try:
            contacts = extract_contacts(
                business,
                website,
            )
            contacts_status = (
                "success"
                if (
                    contacts.contact_person
                    or contacts.contact_emails
                    or contacts.phone_numbers
                )
                else "partial"
            )
        except Exception:
            logger.exception(
                "Contact extraction failed for lead %s",
                business.lead_id,
            )
            contacts = ContactExtraction(
                lead_id=business.lead_id,
            )
            contacts_status = "not_available"
        # --------------------------------------------------------------
        # SOCIAL EXTRACTION
        # --------------------------------------------------------------
        try:
            social = extract_social_media(
                business,
                website,
            )
            social_status = (
                "success"
                if any(
                    getattr(social, platform, None)
                    for platform in (
                        "facebook",
                        "instagram",
                        "linkedin",
                        "twitter",
                    )
                )
                else "partial"
            )
        except Exception:
            logger.exception(
                "Social extraction failed for lead %s",
                business.lead_id,
            )
            social = SocialMediaExtraction(
                lead_id=business.lead_id,
                field_sources={},
            )
            social_status = "not_available"
        # --------------------------------------------------------------
        # TECHNOLOGY DETECTION
        # --------------------------------------------------------------
        try:
            technology = detect_technologies(
                website
            )
            technology_status = (
                "success"
                if technology.technologies
                else "partial"
            )
        except Exception:
            logger.exception(
                "Technology detection failed for lead %s",
                business.lead_id,
            )
            technology = TechnologyExtraction(
                lead_id=business.lead_id,
            )
            technology_status = "not_available"
        # --------------------------------------------------------------
        # SERIALIZE COMPONENTS
        # --------------------------------------------------------------
        business_payload = business.model_dump(
            mode="json"
        )
        profile_payload = profile.model_dump(mode="json")
        website_payload = self._website_payload(
            website,
            technology,
        )
        contacts_payload = self._contact_payload(
            contacts
        )
        social_payload = self._social_payload(
            social
        )
        # --------------------------------------------------------------
        # EXTRACTION METADATA
        # --------------------------------------------------------------
        metadata = {
            "module_status": {
                "business_discovery": "success",
                "website": self._website_module_status(
                    website
                ),
                "profile": profile_status,
                "contacts": contacts_status,
                "social": social_status,
                "technology": technology_status,
            },
            "overall_status": self._overall_status(
                profile_status=profile_status,
                contacts_status=contacts_status,
                social_status=social_status,
                technology_status=technology_status,
                website_status=self._website_module_status(
                    website
                ),
            ),
            "extraction_status": "completed",
        }
        # --------------------------------------------------------------
        # FINAL ENRICHED LEAD
        # --------------------------------------------------------------
        return {
            "lead_id": business.lead_id,
            "business": business_payload,
            "profile": profile_payload,
            "website_analysis": website_payload,
            "contacts": contacts_payload,
            "social_links": social_payload,
            "extraction_metadata": metadata,
        }

    @staticmethod
    def _website_payload(
        site: WebsiteCrawlResult,
        technology: TechnologyExtraction | None = None,
    ) -> dict[str, Any]:
        return {
            "status": site.website_status.value,
            "website_url": site.website_url,
            "website_content": [
                page.model_dump(mode="json")
                for page in site.website_content
            ],
            "about": site.about,
            "services": site.services,
            "contact_page_url": site.contact_page_url,
            "technology_stack": (
                [
                    item.model_dump(mode="json")
                    for item in technology.technologies
                ]
                if technology
                else []
            ),
            "pages_visited": site.pages_visited,
            "crawl_errors": [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in site.crawl_errors
            ],
        }

    @staticmethod
    def _contact_payload(
        contact: ContactExtraction,
    ) -> dict[str, Any]:
        return {
            "contact_person": (
                contact.contact_person.model_dump(
                    mode="json"
                )
                if contact.contact_person
                else None
            ),
            "emails": [
                item.model_dump(mode="json")
                for item in contact.contact_emails
            ],
            "phone_numbers": [
                item.model_dump(mode="json")
                for item in contact.phone_numbers
            ],
            "contact_page_url": (
                contact.contact_page_url
            ),
        }

    @staticmethod
    def _social_payload(
        social: SocialMediaExtraction,
    ) -> dict[str, Any]:
        return {
            platform: (
                getattr(
                    social,
                    platform,
                ).model_dump(mode="json")
                if getattr(
                    social,
                    platform,
                    None,
                )
                else None
            )
            for platform in (
                "facebook",
                "instagram",
                "linkedin",
                "twitter",
            )
        }

    @staticmethod
    def _website_module_status(
        website: WebsiteCrawlResult,
    ) -> str:
        if website.website_status in {
            WebsiteStatus.ACTIVE,
        }:
            return "success"
        if website.website_content:
            return "partial"
        if website.website_status in {
            WebsiteStatus.NOT_FOUND,
            WebsiteStatus.INVALID_URL,
        }:
            return "not_available"
        return "partial"

    @staticmethod
    def _overall_status(
        *,
        website_status: str,
        profile_status: str,
        contacts_status: str,
        social_status: str,
        technology_status: str,
    ) -> str:
        statuses = {
            website_status,
            profile_status,
            contacts_status,
            social_status,
            technology_status,
        }
        if statuses == {"success"}:
            return "success"
        if "success" in statuses or "partial" in statuses:
            return "partial"
        return "not_available"

    def _deduplicate_records(
        self,
        records: list[BusinessRecord],
    ) -> list[BusinessRecord]:
        started = perf_counter()
        unique: list[BusinessRecord] = []
        seen: set[str] = set()
        for record in records:
            normalized_name = re.sub(
                r"\s+",
                " ",
                record.business_name.casefold(),
            ).strip()
            identities = [
                (
                    f"place:{record.place_id}"
                    if record.place_id
                    else f"lead:{record.lead_id}"
                )
            ]
            if record.address:
                name_address = (
                    f"name-address:"
                    f"{normalized_name}|"
                    f"{record.address.casefold().strip()}"
                )
                identities.append(name_address)
            if any(identity in seen for identity in identities):
                continue
            seen.update(identities)
            unique.append(record)
        self.diagnostics["normalization_deduplication_seconds"] = (
            self.diagnostics.get("normalization_deduplication_seconds", 0.0) + perf_counter() - started
        )
        return unique


DAYS = {
    "mon": "Monday", "monday": "Monday",
    "tue": "Tuesday", "tues": "Tuesday", "tuesday": "Tuesday",
    "wed": "Wednesday", "weds": "Wednesday", "wednesday": "Wednesday",
    "thu": "Thursday", "thur": "Thursday", "thurs": "Thursday", "thursday": "Thursday",
    "fri": "Friday", "friday": "Friday",
    "sat": "Saturday", "saturday": "Saturday",
    "sun": "Sunday", "sunday": "Sunday",
}


DAY_PATTERN = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tues?|Wed|Weds|Thurs?|Thu|Fri|Sat|Sun)"


TIME_PATTERN = r"(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\d{1,2}:\d{2})"


HOURS_RE = re.compile(
    rf"(?P<days>{DAY_PATTERN}(?:\s*-\s*{DAY_PATTERN})?)\s*:\s*"
    rf"(?P<schedule>closed|{TIME_PATTERN}\s*(?:-|to)\s*{TIME_PATTERN})",
    re.IGNORECASE,
)


CUSTOMER_RE = re.compile(
    r"\b(?:we\s+serve|serves|our\s+(?:customers|clients|patients)\s+include|designed\s+for|built\s+for)\s+([^.;\n]{3,100})",
    re.IGNORECASE,
)


SERVICE_LEAD_RE = re.compile(r"\b(?:we\s+(?:provide|offer|deliver)|(?:our\s+)?services?\s+include|we\s+speciali[sz]e\s+in)\s+(.+)", re.IGNORECASE)


PRODUCT_LEAD_RE = re.compile(r"\b(?:products?\s+include|we\s+(?:sell|make|manufacture|offer))\s+(.+)", re.IGNORECASE)


GENERIC_HEADINGS = {
    "about", "about us", "our story", "services", "our services", "what we do",
    "our dental services", "dental services", "procedures", "our procedures",
    "products", "our products", "contact", "contact us", "faq", "frequently asked questions",
}


NON_SERVICE_LABELS = {
    "branch", "branches", "location", "locations", "learn more", "read more", "book now",
    "contact", "contact us", "appointment", "appointments", "for teeth", "teeth",
}


CUSTOMER_GROUPS = (
    ("children", re.compile(r"\b(?:children|child|kids|pediatric patients?)\b", re.I)),
    ("adults", re.compile(r"\b(?:adults?|adult patients?)\b", re.I)),
    ("families", re.compile(r"\b(?:famil(?:y|ies))\b", re.I)),
)


CUSTOMER_CATEGORY_ENDINGS = re.compile(
    r"\b(?:patients?|children|kids|adults?|families|business(?:es)?|companies|"
    r"organizations|organisations|nonprofits?|retailers|homeowners|students|"
    r"clients?|customers?|entrepreneurs|visitors|guests)\b$", re.I,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n?-*")


def _unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value)
        key = clean.casefold()
        if clean and key not in seen:
            output.append(clean)
            seen.add(key)
    return output


def _explode_offerings(value: str) -> list[str]:
    """Split explicit enumerations while retaining multiword offering names."""
    value = re.sub(r"^(?:include|including|such as)\s+", "", value.strip(), flags=re.I)
    value = re.sub(r"^(?:a|an)\s+(?:wide|full|comprehensive)\s+range\s+of\s+[^,]+,?\s*(?:including\s+)?", "", value, flags=re.I)
    value = re.sub(r"^.*?\bincluding\s+", "", value, flags=re.I) if re.match(r"^(?:a|an)\s+(?:wide|full|comprehensive)\s+range", value, re.I) else value
    value = re.sub(r"[.!?].*$", "", value)
    pieces = re.split(r"\s*,\s*|\s+(?:and|&)\s+", value)
    return [item for item in (_clean(piece) for piece in pieces) if item and len(item) <= 100]


def _page_lines(page: WebsitePage) -> list[str]:
    return [_clean(line) for line in page.main_text.splitlines() if _clean(line)]


def _extract_offerings(pages: list[WebsitePage], kind: str) -> list[ProfileFact]:
    page_types = {"services"} if kind == "service" else {"products"}
    heading_names = ({"services", "our services", "what we do", "our dental services", "dental services",
                      "procedures", "our procedures"} if kind == "service" else {"products", "our products"})
    lead_re = SERVICE_LEAD_RE if kind == "service" else PRODUCT_LEAD_RE
    collected: list[tuple[str, str]] = []
    for page in pages:
        lines = _page_lines(page)
        if page.page_type not in page_types and not any(line.casefold() in heading_names for line in lines):
            continue
        in_section = page.page_type in page_types
        for line in lines:
            lower = line.casefold().strip(":")
            if lower in GENERIC_HEADINGS:
                in_section = lower in heading_names
                continue
            match = lead_re.search(line)
            if match:
                collected.extend((value, page.page_url) for value in _explode_offerings(match.group(1)))
            elif in_section and 2 <= len(line) <= 100 and not line.endswith((".", "?", "!")):
                # A short heading/list item under an explicit offerings page/section.
                collected.append((line, page.page_url))
    grouped: dict[str, ProfileFact] = {}
    for value, source in collected:
        clean = _clean(value)
        low = clean.casefold().strip(" .,:;!?-")
        if (not clean or low in GENERIC_HEADINGS or low in NON_SERVICE_LABELS
                or re.fullmatch(r"[\d+%., -]+", clean)
                or re.match(r"^(?:for|and|or|with|of|to)\b", low)
                or re.search(r"\b(?:branches|branch|locations|learn more|read more|call us)\b", low)):
            continue
        key = clean.casefold()
        if key not in grouped:
            grouped[key] = ProfileFact(value=clean, source_urls=[source])
        elif source not in grouped[key].source_urls:
            grouped[key].source_urls.append(source)
    return list(grouped.values())




def _extract_customers(pages: list[WebsitePage]) -> list[ProfileFact]:
    grouped: dict[str, ProfileFact] = {}
    for page in pages:
        for match in CUSTOMER_RE.finditer(page.main_text):
            segment = _clean(match.group(1))
            segment = re.split(r"\b(?:to|by|through|with|who|that|seeking|looking|so that)\b", segment,
                               maxsplit=1, flags=re.I)[0].strip(" ,:.-")
            phrase_words = segment.split()
            matching_groups = [(label, pattern) for label, pattern in CUSTOMER_GROUPS if pattern.search(segment)]
            if (not matching_groups and segment and len(phrase_words) <= 8 and CUSTOMER_CATEGORY_ENDINGS.search(segment)
                    and not re.search(r"\b(?:provide|providing|help|helping|achieve|maintain|receive|"
                                      r"experience|treatment|offer|offering|designed|located)\b", segment, re.I)):
                key = segment.casefold()
                if key not in grouped:
                    grouped[key] = ProfileFact(value=segment, source_urls=[page.page_url])
                elif page.page_url not in grouped[key].source_urls:
                    grouped[key].source_urls.append(page.page_url)
            for label, _pattern in matching_groups:
                if label not in grouped:
                    grouped[label] = ProfileFact(value=label, source_urls=[page.page_url])
                elif page.page_url not in grouped[label].source_urls:
                    grouped[label].source_urls.append(page.page_url)
    return list(grouped.values())


def _expand_days(expression: str) -> list[str]:
    parts = re.split(r"\s*[-?]\s*", expression)
    if len(parts) == 1:
        day = DAYS.get(parts[0].lower())
        return [day] if day else []
    first, last = DAYS.get(parts[0].lower()), DAYS.get(parts[1].lower())
    order = list(dict.fromkeys(DAYS.values()))
    if first not in order or last not in order:
        return []
    start, end = order.index(first), order.index(last)
    return order[start:end + 1] if start <= end else []


def _normalize_time(value: str) -> str:
    clean = re.sub(r"\s+", " ", value.strip().lower()).replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", clean)
    if not match:
        return _clean(value)
    hour, minute, meridiem = match.groups()
    return f"{int(hour):02d}:{minute or '00'}" + (f" {meridiem.upper()}" if meridiem else "")


def _extract_hours(pages: list[WebsitePage]) -> list[OperatingHours]:
    output: list[OperatingHours] = []
    seen: set[tuple[str, str | None, str | None, bool]] = set()
    for page in pages:
        for line in _page_lines(page):
            match = HOURS_RE.search(line)
            if not match:
                continue
            schedule = match.group("schedule")
            closed = schedule.casefold() == "closed"
            times = re.split(r"\s*(?:-|to)\s*", schedule, maxsplit=1, flags=re.I) if not closed else []
            opens = _normalize_time(times[0]) if times else None
            closes = _normalize_time(times[1]) if len(times) > 1 else None
            for day in _expand_days(match.group("days")):
                identity = (day, opens, closes, closed)
                if identity not in seen:
                    seen.add(identity)
                    output.append(OperatingHours(day=day, opens=opens, closes=closes, closed=closed, source_url=page.page_url))
    return output


def _about_facts(pages: list[WebsitePage]) -> list[ProfileFact]:
    output: list[ProfileFact] = []
    seen: set[str] = set()
    for page in pages:
        if page.page_type not in {"about", "home"} or not page.main_text:
            continue
        lines = []
        for line in _page_lines(page):
            low = line.casefold()
            if len(line) < 45 or len(line) > 360 or low in GENERIC_HEADINGS or any(term in low for term in (
                "what our patients say", "testimonials", "happy stories", "book an appointment",
                "call us today", "read more", "gallery", "copyright", "privacy policy",
                "home services about contact", "all rights reserved", "cookie policy",
            )):
                continue
            lines.append(line)
            if len(lines) == 3:
                break
        text = _clean(" ".join(lines))
        if not text:
            continue
        if text.casefold() not in seen:
            output.append(ProfileFact(value=text, source_urls=[page.page_url]))
            seen.add(text.casefold())
    return output




def _description(business: BusinessRecord, pages: list[WebsitePage]) -> ProfileFact | None:
    # Prefer explicit, page-authored metadata; retain it verbatim rather than inventing claims.
    for page in pages:
        if page.page_type in {"home", "about"} and page.meta_description:
            return ProfileFact(value=_clean(page.meta_description)[:320], source_urls=[page.page_url])
    # A verified source-record description is acceptable and keeps its original provenance.
    if business.description and business.source_ref:
        return ProfileFact(value=_clean(business.description), source_urls=[business.source_ref])
    for page in pages:
        if page.page_type in {"home", "about"}:
            for line in _page_lines(page):
                if line.casefold() not in GENERIC_HEADINGS and len(line) >= 35:
                    return ProfileFact(value=line[:320], source_urls=[page.page_url])
    return None


def build_business_profile(business: BusinessRecord, website: WebsiteCrawlResult) -> BusinessProfile:
    """Build a conservative, source-linked profile from already-crawled page content."""
    if business.lead_id != website.lead_id:
        raise ValueError("business and website result lead_id values must match")
    pages = [page for page in website.website_content if page.main_text.strip()]
    profile = BusinessProfile(
        lead_id=business.lead_id,
        business_name=business.business_name,
        services=_extract_offerings(pages, "service"),
        products=_extract_offerings(pages, "product"),
        target_customers=_extract_customers(pages),
        about_info=_about_facts(pages),
        business_description=_description(business, pages),
        operating_hours=_extract_hours(pages),
    )
    profile.field_sources = {
        "services": _sources(profile.services),
        "products": _sources(profile.products),
        "target_customers": _sources(profile.target_customers),
        "about_info": _sources(profile.about_info),
        "business_description": profile.business_description.source_urls if profile.business_description else [],
        "operating_hours": _unique_sources(entry.source_url for entry in profile.operating_hours),
    }
    return profile


def _sources(facts: list[ProfileFact]) -> list[str]:
    return _unique_sources(url for fact in facts for url in fact.source_urls)


def _unique_sources(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+", re.I)


PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{5,}\d)(?:\s*(?:ext\.?|x)\s*\d{1,6})?(?!\w)", re.I)


PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "yourdomain.com", "email.com"}


SYSTEM_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster"}


PLACEHOLDER_LOCAL_PARTS = {"name", "yourname", "user", "email", "youremail", "test", "example", "john.doe", "jane.doe"}


PERSON_RE = re.compile(
    r"^\s*(?:contact\s+person|primary\s+contact|contact|owner|founder|practice\s+manager|"
    r"for\s+(?:business\s+)?inquiries,?\s*contact)\s*:\s*"
    r"(?P<name>(?:Dr\.?\s+|Mr\.?\s+|Ms\.?\s+|Mrs\.?\s+)?[A-Z][A-Za-z'?-]+(?:\s+[A-Z][A-Za-z'?-]+){1,3})\s*$",
    re.I | re.M,
)


def _valid_email(raw: str) -> str | None:
    address = unquote(raw.strip().strip(".,;:<>[](){}").lower())
    if not EMAIL_RE.fullmatch(address):
        return None
    local, domain = address.rsplit("@", 1)
    if domain in PLACEHOLDER_DOMAINS or "." not in domain:
        return None
    if local.casefold() in SYSTEM_LOCAL_PARTS | PLACEHOLDER_LOCAL_PARTS:
        return None
    if any(token in domain for token in ("sentry.io", "wixpress.com", "wordpress.com", "shopifyemail.com")):
        return None
    return address


def _phone(raw: str) -> tuple[str, str] | None:
    original = re.sub(r"\s+", " ", raw).strip(" .,:;")
    digits = re.sub(r"\D", "", original)
    if not 7 <= len(digits) <= 15 or len(set(digits)) == 1:
        return None
    normalized = ("+" if original.startswith("+") else "") + digits
    return original, normalized




def _phone_key(normalized: str) -> str:
    digits = normalized.lstrip("+")
    # US country code 1 is often omitted on the same listed number.
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def extract_contacts(business: BusinessRecord, website: WebsiteCrawlResult) -> ContactExtraction:
    """Extract contact data only from the given business and previously collected pages."""
    if business.lead_id != website.lead_id:
        raise ValueError("business and website result lead_id values must match")
    emails: OrderedDict[str, list[str]] = OrderedDict()
    phones: OrderedDict[str, tuple[str, str, list[str]]] = OrderedDict()
    person: ContactValue | None = None
    for page in website.website_content:
        content = page.main_text
        contact_text = getattr(page, "contact_text", "") or ""
        path = urlparse(page.page_url).path.casefold()
        page_kind = page.page_type.casefold()
        person_source = page_kind in {"home", "about", "contact", "team"} or bool(
            re.search(r"/(?:about|our-story|contact(?:-us)?|contactus|get-in-touch|reach-out|team|people)(?:/|$)", path)
        )
        phone_source = page_kind in {"home", "about", "contact", "team", "services", "faq"} or bool(
            re.search(r"/(?:about|our-story|contact(?:-us)?|contactus|get-in-touch|reach-out|team|people)(?:/|$)", path)
        )
        if re.search(r"/(?:blog|news|articles?|posts?)(?:/|$)", path):
            content = ""
        contact_content = "\n".join(value for value in (content, contact_text) if value)
        for link in page.outgoing_links:
            parsed = urlparse(link.url)
            if parsed.scheme.lower() in {"mailto", "tel"}:
                contact_content += " " + unquote(parsed.path)
        for raw in EMAIL_RE.findall(contact_content):
            email = _valid_email(raw)
            if email:
                emails.setdefault(email, [])
                if page.page_url not in emails[email]:
                    emails[email].append(page.page_url)
        for link in page.outgoing_links:
            parsed = urlparse(link.url)
            if parsed.scheme.lower() == "tel":
                found = _phone(unquote(parsed.path))
                if found:
                    original, normalized = found
                    key = _phone_key(normalized)
                    phones.setdefault(key, (original, normalized, []))
                    if page.page_url not in phones[key][2]:
                        phones[key][2].append(page.page_url)
        phone_text = contact_text
        if phone_source:
            phone_text += "\n" + content
        for raw in PHONE_RE.findall(phone_text):
            found = _phone(raw)
            if found:
                original, normalized = found
                key = _phone_key(normalized)
                phones.setdefault(key, (original, normalized, []))
                if page.page_url not in phones[key][2]:
                    phones[key][2].append(page.page_url)
        if person is None and person_source:
            match = PERSON_RE.search(content)
            if match:
                person = ContactValue(value=re.sub(r"\s+", " ", match.group("name")).strip(), source_urls=[page.page_url])
    record_source = business.source_url or business.source_ref or business.website
    if business.email and record_source:
        value = _valid_email(business.email)
        if value:
            emails.setdefault(value, [])
            if record_source not in emails[value]:
                emails[value].append(record_source)
    if business.phone and record_source:
        found = _phone(business.phone)
        if found:
            original, normalized = found
            key = _phone_key(normalized)
            phones.setdefault(key, (original, normalized, []))
            if record_source not in phones[key][2]:
                phones[key][2].append(record_source)
    email_records = [ContactEmail(email=value, source_urls=sources) for value, sources in emails.items()]
    phone_records = [ContactPhone(value=value, normalized=normalized, source_urls=sources) for value, normalized, sources in phones.values()]
    result = ContactExtraction(
        lead_id=business.lead_id, contact_person=person, contact_emails=email_records,
        phone_numbers=phone_records, contact_page_url=website.contact_page_url,
        email=email_records[0].email if email_records else None,
        phone=phone_records[0].normalized if phone_records else None,
    )
    result.field_sources = {
        "contact_person": person.source_urls if person else [],
        "contact_emails": list(dict.fromkeys(url for item in email_records for url in item.source_urls)),
        "phone_numbers": list(dict.fromkeys(url for item in phone_records for url in item.source_urls)),
        "contact_page_url": [website.contact_page_url] if website.contact_page_url else [],
    }
    return result


PLATFORMS = {
    "facebook": {"facebook.com"},
    "instagram": {"instagram.com"},
    "linkedin": {"linkedin.com"},
    "twitter": {"twitter.com", "x.com"},
}


IGNORE_SLUGS = {"home", "share", "intent", "login", "signup", "explore", "hashtag", "sharer", "plugins"}


STOP_WORDS = {"the", "and", "of", "for", "inc", "llc", "ltd", "limited", "company", "co", "studio", "official"}


NON_PROFILE_PATHS = {"posts", "post", "reel", "reels", "stories", "story", "photos", "photo", "watch",
                     "events", "groups", "dialog", "accounts", "p", "status", "search", "feed"}


def _normalize_social_url(url: str, allowed_hosts: set[str]) -> str | None:
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.lower().removeprefix("www.")
        if host not in allowed_hosts:
            return None
        path = re.sub(r"/+", "/", parsed.path).rstrip("/")
        if not path or path.casefold() in {"/home", "/share", "/intent", "/login", "/explore"}:
            return None
        parts = [part.casefold() for part in path.strip("/").split("/") if part]
        first = parts[0]
        if first in IGNORE_SLUGS or first in NON_PROFILE_PATHS or first.endswith(".php"):
            return None
        if host in {"instagram.com", "twitter.com", "x.com"} and len(parts) != 1:
            return None
        if host == "linkedin.com" and (len(parts) != 2 or first not in {"company", "in", "school"}):
            return None
        if host == "facebook.com" and (len(parts) > 3 or any(part in NON_PROFILE_PATHS for part in parts)):
            return None
        return urlunparse(("https", host, path, "", "", ""))
    except (ValueError, UnicodeError):
        return None


def _business_tokens(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", name.casefold()) if len(token) > 2 and token not in STOP_WORDS}


def extract_social_media(business: BusinessRecord, website: WebsiteCrawlResult) -> SocialMediaExtraction:
    """Find social accounts explicitly linked from the stored official-site pages."""
    if business.lead_id != website.lead_id:
        raise ValueError("business and website result lead_id values must match")
    found: dict[str, SocialAccount | None] = {platform: None for platform in PLATFORMS}
    business_tokens = _business_tokens(business.business_name)
    for page in website.website_content:
        for link in page.outgoing_links:
            parsed = urlparse(link.url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            platform = next((name for name, hosts in PLATFORMS.items() if host in hosts), None)
            if not platform or found[platform] is not None:
                continue
            normalized = _normalize_social_url(link.url, PLATFORMS[platform])
            if not normalized:
                continue
            path_tokens = set(re.findall(r"[a-z0-9]+", urlparse(normalized).path.casefold()))
            label_tokens = _business_tokens(link.text or "")
            if business_tokens and not (business_tokens & path_tokens or business_tokens & label_tokens):
                continue
            found[platform] = SocialAccount(url=normalized, source_url=page.page_url)
    result = SocialMediaExtraction(lead_id=business.lead_id, **found, field_sources={})
    result.field_sources = {
        platform: [account.source_url] if account else []
        for platform, account in found.items()
    }
    return result


RULES: dict[str, tuple[str, ...]] = {
    "WordPress": ("meta-generator:wordpress", "/wp-content/", "/wp-includes/"),
    "Shopify": ("cdn.shopify.com", "shopify-section", "header:x-shopify-stage:"),
    "Wix": ("wixstatic.com", "meta-generator:wix", "wix.com/"),
    "React": ("data-reactroot", "react-dom", "react.production.min.js"),
    "Next.js": ("/_next/", "__next_data__", "header:x-powered-by:next.js"),
    "Google Analytics": ("googletagmanager.com", "google-analytics.com", "gtag("),
    "Webflow": ("webflow.js", "meta-generator:webflow"),
    "Squarespace": ("static1.squarespace.com", "meta-generator:squarespace"),
    "Drupal": ("meta-generator:drupal", "/sites/default/files/"),
    "Joomla": ("meta-generator:joomla", "/media/system/js/"),
    "Bootstrap": ("bootstrap.min.css", "bootstrap.min.js"),
}


def detect_technologies(website: WebsiteCrawlResult) -> TechnologyExtraction:
    """Detect technologies from evidence captured during Part 2 crawling."""
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"evidence": [], "source_urls": []})
    for page in website.website_content:
        signals = list(page.technology_signals)
        signals.extend(f"header:{key.lower()}:{value}" for key, value in page.response_headers.items())
        normalized_signals = [signal.casefold() for signal in signals]
        for technology, signatures in RULES.items():
            matches = [
                original for original, normalized in zip(signals, normalized_signals)
                if any(signature in normalized for signature in signatures)
            ]
            if matches:
                bucket = grouped[technology]
                bucket["evidence"].extend(item for item in matches if item not in bucket["evidence"])
                if page.page_url not in bucket["source_urls"]:
                    bucket["source_urls"].append(page.page_url)
    items = [
        DetectedTechnology(name=name, evidence=data["evidence"], source_urls=data["source_urls"])
        for name, data in sorted(grouped.items())
    ]
    sources = list(dict.fromkeys(url for item in items for url in item.source_urls))
    return TechnologyExtraction(lead_id=website.lead_id, technologies=items, field_sources={"technologies": sources})






def canonical_lead_output(lead: Any) -> LeadResult:
    """Map existing extracted facts to the new API contract without re-extracting."""
    data = _as_dict(lead)
    business = _as_dict(data.get("business"))
    profile = _as_dict(data.get("profile"))
    website = _as_dict(data.get("website_analysis"))
    contacts = _as_dict(data.get("contacts"))
    social = _as_dict(data.get("social_links"))
    about = " ".join(_public_string_list(profile.get("about_info")))
    if not about:
        about = " ".join(_public_string_list(website.get("about")))
    return LeadResult(
        lead_id=data.get("lead_id") or business.get("lead_id"),
        discovery=business,
        enrichment={
            "website_status": website.get("status") or "not_checked",
            "website_url": website.get("website_url"),
            "about": about,
            "business_description": _public_scalar(profile.get("business_description")),
            "services": _public_string_list(profile.get("services")),
            "products": _public_string_list(profile.get("products")),
            "target_customers": _public_string_list(profile.get("target_customers")),
            "contact_person": _public_scalar(contacts.get("contact_person")),
            "emails": _public_string_list(contacts.get("emails"), ("email", "value", "text")),
            "phone_numbers": _public_string_list(contacts.get("phone_numbers"), ("normalized", "phone", "value", "text")),
            "social_links": {
                platform: _public_social(social.get(platform))
                for platform in ("facebook", "instagram", "linkedin", "twitter")
            },
            "technology_stack": _public_string_list(website.get("technology_stack"), ("name", "technology", "value", "text")),
            "contact_page_url": website.get("contact_page_url") or contacts.get("contact_page_url"),
        },
        scoring=_as_dict(data.get("lead_scoring")),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    """Return a plain dictionary without exposing arbitrary nested fields."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}


def _public_scalar(value: Any, keys: tuple[str, ...] = ("value", "text", "name", "url")) -> Any:
    """Extract one public primitive value from an extractor record."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float, bool)):
                return candidate
    return None


def _public_string_list(value: Any, keys: tuple[str, ...] = ("value", "text", "name")) -> list[str]:
    """Convert extractor records to strings and discard source/evidence metadata."""
    if value is None:
        return []
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    items = value if isinstance(value, list) else [value]
    output: list[str] = []
    for item in items:
        text = _public_scalar(item, keys)
        if isinstance(text, str) and text.strip():
            cleaned = text.strip()
            if cleaned not in output:
                output.append(cleaned)
    return output


def _public_social(value: Any) -> str | None:
    """Return only a social profile URL."""
    candidate = _public_scalar(value, ("url", "value"))
    return candidate if isinstance(candidate, str) else None
