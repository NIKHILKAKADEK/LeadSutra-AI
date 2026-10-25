"""Thin service layer for AI research, knowledge retrieval, and proposal generation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents.lead_pipeline.schemas import LeadResult
from app.agents.proposal_agent import proposal_agent
from app.agents.rag_agent import rag_agent, index_lead_knowledge
from app.agents.research_agent import research_agent
from app.core.config import get_settings
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
    """Crawl the website if a URL is available and content has not yet been fetched."""
    url = adapted.get("website")
    if not url or adapted.get("about_info") or adapted.get("services"):
        return adapted

    clean_url = normalize_url(url)
    if not clean_url:
        return adapted

    try:
        from app.agents.lead_pipeline.schemas import BusinessRecord
        crawler = WebsiteCrawler()
        crawl_result = await crawler.crawl(BusinessRecord(
            lead_id=adapted.get("lead_id") or "research-lead",
            business_name=adapted.get("business_name") or "Business",
            website=clean_url,
        ))
        if crawl_result.website_content:
            page_texts = [p.main_text for p in crawl_result.website_content if p.main_text]
            if page_texts:
                adapted["description"] = (adapted.get("description") or "") + "\n\n" + page_texts[0][:400]
            if crawl_result.services:
                adapted["services"] = list(dict.fromkeys(
                    adapted.get("services", []) + [s["text"] for s in crawl_result.services]
                ))
            if crawl_result.about:
                adapted["about_info"] = " ".join([a["text"] for a in crawl_result.about])[:500]
    except Exception as exc:
        logger.warning("Could not crawl website %s during research: %s", url, exc)

    return adapted


def analyze_lead(lead: LeadResult) -> dict[str, Any]:
    """Analyze a single lead synchronously with strict factual grounding."""
    adapted = adapt_lead(lead)
    try:
        # If in a worker thread without an active event loop, run crawler enrichment
        asyncio.get_running_loop()
    except RuntimeError:
        adapted = asyncio.run(_enrich_website_if_needed(adapted))

    result = research_agent(adapted)

    try:
        ResearchOutputService(get_settings().research_root).save(lead.lead_id, result)
    except Exception as exc:
        logger.warning("Could not persist research artifact for lead %s: %s", lead.lead_id, exc)

    # Automatically index into RAG vector store for this lead
    try:
        index_lead_knowledge(
            lead_id=lead.lead_id,
            business_name=lead.discovery.business_name,
            research=result,
        )
    except Exception as exc:
        logger.warning("Could not automatically index lead %s in RAG: %s", lead.lead_id, exc)

    return result


async def analyze_lead_async(lead: LeadResult) -> dict[str, Any]:
    """Asynchronous research analysis including live website crawling."""
    adapted = adapt_lead(lead)
    adapted = await _enrich_website_if_needed(adapted)
    result = await asyncio.to_thread(research_agent, adapted)

    try:
        await asyncio.to_thread(
            ResearchOutputService(get_settings().research_root).save,
            lead.lead_id,
            result,
        )
    except Exception as exc:
        logger.warning("Could not persist research artifact for lead %s: %s", lead.lead_id, exc)

    try:
        await asyncio.to_thread(
            index_lead_knowledge,
            lead_id=lead.lead_id,
            business_name=lead.discovery.business_name,
            research=result,
        )
    except Exception as exc:
        logger.warning("Could not automatically index lead %s in RAG: %s", lead.lead_id, exc)

    return result


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
    """Generate proposal and persist to disk for Voice/Email compatibility."""
    result = proposal_agent(
        adapt_lead(lead),
        research=research,
        retrieved_context=retrieved_context,
    )

    if persist:
        try:
            store = ProposalJsonService(get_settings().proposal_root)
            store.save(lead_id=lead.lead_id, proposal=result, rich_proposal=result)
        except Exception as exc:
            logger.warning("Could not persist proposal artifact for lead %s: %s", lead.lead_id, exc)

    return result
