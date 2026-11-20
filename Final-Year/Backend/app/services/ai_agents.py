from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.agents.lead_pipeline.schema import (
    BrowserConfig,
    LeadResult,
    PlacesConfig,
)
from app.agents.proposal.agent import proposal_agent
from app.agents.rag.agent import rag_agent, index_lead_knowledge
from app.agents.research.agent import research_agent
from app.core.config import DiscoverySettings, get_settings
from app.integrations.google_places import (
    GooglePlacesClient,
    PlacesConfigurationError,
)
from app.integrations.maps_scraper import GoogleMapsBrowserDiscovery
from app.integrations.website_fetcher import WebsiteCrawler, normalize_url
from app.services.lead_results import LeadResultStore
from app.services.proposals import ProposalJsonService
from app.services.research_outputs import ResearchOutputService
from app.tools.lead_adapter import adapt_lead

logger = logging.getLogger(__name__)


def resolve_lead(lead: LeadResult | None, lead_id: str | None) -> LeadResult:
    if lead is not None:
        return lead
    if not lead_id:
        raise ValueError("Provide a lead record or lead_id.")
    stored = LeadResultStore(get_settings().lead_json_path).get_by_id(lead_id)
    if stored is None:
        raise LookupError("No saved lead was found with that lead_id.")
    return stored


async def _enrich_website_if_needed(adapted: dict[str, Any]) -> dict[str, Any]:
    """Refresh bounded website evidence for this research run when a URL exists."""
    url = adapted.get("website")
    if not url:
        return adapted

    clean_url = normalize_url(url)
    if not clean_url:
        return adapted

    try:
        from app.agents.lead_pipeline.schema import (
            BusinessRecord,
            WebsiteCrawlerConfig,
        )
        crawler = WebsiteCrawler(
            config=WebsiteCrawlerConfig(
                max_pages=6,
                timeout_seconds=6.0,
                crawl_timeout_seconds=18.0,
                concurrency=3,
            )
        )
        crawl_result = await crawler.crawl(BusinessRecord(
            lead_id=adapted.get("lead_id") or "research-lead",
            business_name=adapted.get("business_name") or "Business",
            website=clean_url,
        ))
        if crawl_result.website_content:
            page_texts = [
                {"page_url": p.page_url, "page_type": p.page_type,
                 "title": p.page_title, "description": p.meta_description,
                 "text": p.main_text}
                for p in crawl_result.website_content if p.main_text
            ]
            if page_texts:
                adapted["website_research_pages"] = page_texts[:6]
                if not adapted.get("description"):
                    adapted["description"] = page_texts[0]["text"][:1200]
                adapted["research_sources"] = [
                    {"title": p.page_title or p.page_type.title(), "url": p.page_url}
                    for p in crawl_result.website_content if p.main_text
                ]
                adapted["profile_extraction_status"] = "complete"
            # Use the lead pipeline's evidence-based extractors so website
            # services, products, audience phrases and hours reach research.
            from app.agents.lead_pipeline.pipeline import (
                _about_facts, _extract_customers, _extract_hours, _extract_offerings,
            )
            services = _extract_offerings(crawl_result.website_content, "service")
            products = _extract_offerings(crawl_result.website_content, "product")
            customers = _extract_customers(crawl_result.website_content)
            about = _about_facts(crawl_result.website_content)
            hours = _extract_hours(crawl_result.website_content)
            adapted["services"] = list(dict.fromkeys(
                adapted.get("services", []) + [fact.value for fact in services]
            ))
            adapted["products"] = list(dict.fromkeys(
                adapted.get("products", []) + [fact.value for fact in products]
            ))
            adapted["target_customers"] = list(dict.fromkeys(
                adapted.get("target_customers", []) + [fact.value for fact in customers]
            ))
            if about and not adapted.get("about_info"):
                adapted["about_info"] = " ".join(fact.value for fact in about)[:1200]
            if hours:
                adapted["operating_hours"] = [item.model_dump(mode="json") for item in hours]
            adapted["contact_page_url"] = crawl_result.contact_page_url
            adapted["about_page_url"] = next(
                (p.page_url for p in crawl_result.website_content if p.page_type == "about"), None
            )
    except Exception as exc:
        logger.warning("Could not crawl website %s during research: %s", url, exc)

    return adapted


def index_research_knowledge(
    lead_id: str,
    business_name: str,
    research: dict[str, Any],
) -> None:
    """Index optional RAG knowledge without delaying the research response."""
    try:
        index_lead_knowledge(
            lead_id=lead_id,
            business_name=business_name,
            research=research,
        )
    except Exception:
        logger.exception("Could not automatically index lead %s in RAG", lead_id)


def analyze_lead(lead: LeadResult) -> dict[str, Any]:
    """Analyze a single lead synchronously with strict factual grounding."""
    adapted = adapt_lead(lead)
    try:
        # If in a worker thread without an active event loop, run crawler enrichment
        asyncio.get_running_loop()
    except RuntimeError:
        adapted = asyncio.run(_enrich_website_if_needed(adapted))

    result = research_agent(adapted)

    ResearchOutputService(get_settings().research_root).save(lead.lead_id, result)

    return result


async def analyze_lead_async(lead: LeadResult) -> dict[str, Any]:
    """Asynchronous research analysis including live website crawling."""
    adapted = adapt_lead(lead)
    adapted = await _enrich_website_if_needed(adapted)
    result = await asyncio.to_thread(research_agent, adapted)

    await asyncio.to_thread(
        ResearchOutputService(get_settings().research_root).save,
        lead.lead_id,
        result,
    )

    await asyncio.to_thread(
        index_research_knowledge,
        lead_id=lead.lead_id,
        business_name=lead.discovery.business_name,
        research=result,
    )

    return result


def get_competitor_analysis(lead_id: str) -> dict[str, Any] | None:
    return ResearchOutputService(get_settings().research_root).load_competitors(lead_id)


async def analyze_competitors(lead: LeadResult) -> dict[str, Any]:
    lead_data = adapt_lead(lead)
    name = lead_data["business_name"]
    category = lead_data.get("category") or lead_data.get("sub_category")
    address = lead_data.get("address")
    latitude = lead_data.get("latitude")
    longitude = lead_data.get("longitude")
    settings = DiscoverySettings()
    if (
        not category
        or not address
        or latitude is None
        or longitude is None
    ):
        analysis = {
            "business_name": name,
            "category": category or "business",
            "location": address or "Not provided",
            "status": "unavailable",
            "source": None,
            "competitors": [],
            "radius_meters": settings.leadsutra_competitor_radius_meters,
            "comparison_summary": "Competitors could not be reliably matched because the lead is missing its category, address, or coordinates.",
            "message": "The lead needs a category, address and map coordinates to confirm competitors are both nearby and in the same business category.",
            "researched_at": datetime.now(timezone.utc).isoformat(),
        }
        ResearchOutputService(get_settings().research_root).save_competitors(lead.lead_id, analysis)
        return analysis

    if not settings.leadsutra_enable_google_places and not settings.leadsutra_enable_maps_browser:
        raise RuntimeError("Google Places and Google Maps browser discovery are both disabled.")

    try:
        records = await asyncio.wait_for(
            _search_competitor_places(
                category,
                address,
                settings,
                latitude,
                longitude,
            ),
            timeout=35,
        )
    except TimeoutError as exc:
        raise RuntimeError("Competitor search exceeded its 35-second time limit.") from exc

    normalize_name = lambda value: re.sub(r"[^a-z0-9]+", "", value.casefold())
    subject = normalize_name(name)
    competitors = []
    seen = set()
    sources = set()
    radius_meters = settings.leadsutra_competitor_radius_meters
    for record in records:
        candidate_name = normalize_name(record.business_name)
        if not candidate_name or candidate_name == subject or candidate_name in seen:
            continue
        candidate_category = record.category or record.sub_category or record.primary_type
        if not candidate_category or not _same_business_category(category, candidate_category):
            continue
        if record.latitude is None or record.longitude is None:
            continue
        distance_meters = _distance_meters(
            latitude,
            longitude,
            record.latitude,
            record.longitude,
        )
        if distance_meters > radius_meters:
            continue
        seen.add(candidate_name)
        sources.add(record.discovery_source or "google_places")
        competitors.append({
            "name": record.business_name,
            "category": candidate_category,
            "address": record.address,
            "rating": record.rating,
            "review_count": record.review_count,
            "website": record.website,
            "phone": record.phone,
            "source_url": record.source_url,
            "distance_meters": round(distance_meters),
        })

    rated = [item["rating"] for item in competitors if item["rating"] is not None]
    summary = (
        f"Found {len(competitors)} businesses matching the {category} category "
        f"within {radius_meters / 1000:g} km of this listing."
    )
    rating = lead_data.get("rating")
    if rated:
        average = sum(rated) / len(rated)
        summary += f" Their average listed rating is {average:.1f}/5."
        if rating is not None:
            summary += f" This business is rated {rating:.1f}/5."
    analysis = {
        "business_name": name,
        "category": category,
        "location": address,
        "status": "complete" if competitors else "no_results",
        "source": ", ".join(sorted(sources)) if sources else None,
        "competitors": competitors,
        "radius_meters": radius_meters,
        "comparison_summary": summary if competitors else (
            f"No same-category listings were found within {radius_meters / 1000:g} km of {name}."
        ),
        "message": None if competitors else "Try refreshing, or verify the business category and map pin.",
        "researched_at": datetime.now(timezone.utc).isoformat(),
    }
    ResearchOutputService(get_settings().research_root).save_competitors(lead.lead_id, analysis)
    return analysis


async def _search_competitor_places(
    category: str,
    location: str,
    settings: DiscoverySettings,
    latitude: float,
    longitude: float,
):
    records = []
    places_error: Exception | None = None
    if settings.leadsutra_enable_google_places:
        client = GooglePlacesClient(config=PlacesConfig.from_env(settings))
        try:
            records = await client.search(
                category,
                location,
                limit=20,
                location_bias=(
                    latitude,
                    longitude,
                    float(settings.leadsutra_competitor_radius_meters),
                ),
            )
        except PlacesConfigurationError as exc:
            places_error = exc
            if not settings.leadsutra_enable_maps_browser:
                raise
        except Exception as exc:
            places_error = exc
            if not settings.leadsutra_enable_maps_browser_fallback:
                raise

    if records:
        return records
    if settings.leadsutra_enable_maps_browser and (
        places_error is not None or settings.leadsutra_maps_fallback_on_zero_results
        or not settings.leadsutra_enable_google_places
    ):
        browser = GoogleMapsBrowserDiscovery(
            browser_config=BrowserConfig(
                navigation_timeout_ms=10_000,
                action_timeout_ms=4_000,
            ),
            scroll_pause_ms=400,
        )
        return await browser.search(category, location, limit=8)
    if places_error is not None:
        raise places_error
    return records


def _same_business_category(requested: str, candidate: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    requested_key = normalize(requested)
    candidate_key = normalize(candidate)
    if requested_key == candidate_key:
        return True
    aliases = {
        "gym": {"gym", "fitness center", "fitness centre", "fitness club"},
        "fitness center": {"gym", "fitness center", "fitness centre", "fitness club"},
        "fitness centre": {"gym", "fitness center", "fitness centre", "fitness club"},
        "dentist": {"dentist", "dental clinic", "dental office"},
        "dental clinic": {"dentist", "dental clinic", "dental office"},
        "cafe": {"cafe", "coffee shop"},
        "coffee shop": {"cafe", "coffee shop"},
    }
    if candidate_key in aliases.get(requested_key, set()):
        return True
    requested_tokens = set(requested_key.split())
    candidate_tokens = set(candidate_key.split())
    if len(requested_tokens) == 1:
        return requested_tokens.issubset(candidate_tokens)
    return bool(requested_tokens & candidate_tokens)


def _distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat_a, lat_b = radians(latitude_a), radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = radians(longitude_b - longitude_a)
    arc = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(arc))


def retrieve_knowledge(
    query: str,
    k: int = 3,
    *,
    lead_id: str | None = None,
) -> list[dict[str, Any]]:
    return rag_agent(query, lead_id=lead_id, k=k)


def create_outreach_proposal(
    lead: LeadResult,
    *,
    research: dict | None = None,
    retrieved_context: list[str | dict[str, str]] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Generate a proposal and persist it in MongoDB for Voice/Email."""
    result = proposal_agent(
        adapt_lead(lead),
        research=research,
        retrieved_context=retrieved_context,
    )

    if persist:
        store = ProposalJsonService(get_settings().proposal_root)
        store.save(lead_id=lead.lead_id, proposal=result, rich_proposal=result)

    return result
