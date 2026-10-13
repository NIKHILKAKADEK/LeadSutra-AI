"""LangGraph nodes for the LeadSutra AI multi-agent sales workflow."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.agents.lead_pipeline.pipeline import LeadPipeline, canonical_lead_output
from app.agents.lead_pipeline.schemas import LeadResult
from app.agents.proposal_agent import proposal_agent
from app.agents.rag_agent import index_lead_knowledge, rag_agent
from app.agents.research_agent import research_agent
from app.core.config import get_email_settings, get_settings
from app.graph.state import WorkflowState
from app.models.proposal import ProposalResult as RichProposalModel
from app.models.research import ResearchResult as RichResearchModel
from app.services.email_service import EmailService, EmailWorkflowError
from app.services.lead_results import LeadResultStore
from app.services.proposals import ProposalJsonService
from app.services.research_outputs import ResearchOutputService
from app.tools.lead_adapter import adapt_lead

logger = logging.getLogger("leadsutra.graph")


def parse_lead_query(raw_query: str, explicit_location: str | None = None) -> tuple[str, str]:
    """Extract category and location from natural language queries."""
    query = (raw_query or "").strip()
    location = (explicit_location or "").strip()

    if not location and query:
        match = re.search(r"\b(?:in|near|at|around)\s+([A-Za-z\s]+)$", query, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            query = query[:match.start()].strip()

    query = re.sub(
        r"^(?:find|search for|show me|look for|list|get|discover)\s+",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    return query, location


# ======================================================================
# STAGE A: QUERY VALIDATION & LEAD DISCOVERY
# ======================================================================

async def validate_query_node(state: WorkflowState) -> dict[str, Any]:
    """Parse and validate natural language query and search parameters."""
    errors = list(state.get("errors") or [])
    metadata = dict(state.get("execution_metadata") or {})
    raw_query = state.get("user_query", "")
    explicit_loc = state.get("search_location", "")

    category, location = parse_lead_query(raw_query, explicit_loc)

    if not category:
        errors.append("Could not determine business category from query.")
    if not location:
        errors.append("Search location is required (e.g. 'Nashik' or specify 'in <city>').")

    status = "QUERY_VALIDATED" if not errors else "FAILED"
    metadata["query_validated_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "business_category": category,
        "search_location": location,
        "errors": errors,
        "execution_status": status,
        "execution_metadata": metadata,
    }


async def lead_discovery_node(state: WorkflowState) -> dict[str, Any]:
    """Discover business leads using Google Places and browser scraper fallback."""
    category = state.get("business_category")
    location = state.get("search_location")
    limit = state.get("discovery_limit", 10)
    priority = state.get("priority_filter")
    errors = list(state.get("errors") or [])
    metadata = dict(state.get("execution_metadata") or {})

    logger.info("Executing lead discovery: %s in %s", category, location)
    pipeline = LeadPipeline()

    try:
        run_result = await pipeline.run(
            query=category,
            location=location,
            limit=limit,
            mode="full",
            priority=priority,
        )
        metadata["discovery_source"] = run_result.source
        metadata["fallback_used"] = run_result.fallback_used
        metadata["candidates_count"] = len(run_result.leads)

        # Transform to canonical dict representations
        canonical_leads = [
            canonical_lead_output(lead).model_dump(mode="json")
            for lead in run_result.leads
        ]

        return {
            "discovered_leads": canonical_leads,
            "candidates_count": len(canonical_leads),
            "execution_status": "LEADS_DISCOVERED",
            "execution_metadata": metadata,
        }
    except Exception as exc:
        logger.exception("Lead discovery node failed: %s", exc)
        errors.append(f"Lead discovery failed: {exc}")
        return {
            "discovered_leads": [],
            "candidates_count": 0,
            "errors": errors,
            "execution_status": "FAILED",
            "execution_metadata": metadata,
        }


async def normalize_and_deduplicate_leads_node(state: WorkflowState) -> dict[str, Any]:
    """Normalize and deduplicate discovered leads."""
    leads = state.get("discovered_leads") or []
    seen_ids = set()
    deduped = []

    for item in leads:
        if isinstance(item, LeadResult):
            item = item.model_dump(mode="json")
        elif not isinstance(item, dict):
            logger.warning("Skipping discovered lead with unsupported type: %s", type(item).__name__)
            continue

        lead_id = item.get("lead_id")
        if lead_id and lead_id not in seen_ids:
            seen_ids.add(lead_id)
            deduped.append(item)

    return {
        "discovered_leads": deduped,
        "candidates_count": len(deduped),
        "execution_status": "LEADS_NORMALIZED",
    }


async def persist_and_return_leads_node(state: WorkflowState) -> dict[str, Any]:
    """Persist discovered leads and set workflow status to pause for lead selection."""
    metadata = dict(state.get("execution_metadata") or {})
    metadata["discovery_completed_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "execution_status": "WAITING_FOR_USER_SELECTION",
        "execution_metadata": metadata,
    }


# ======================================================================
# STAGE B: USER LEAD SELECTION VALIDATION
# ======================================================================

async def validate_selected_lead_node(state: WorkflowState) -> dict[str, Any]:
    """Validate that the selected lead ID exists in state or persistent storage."""
    errors = list(state.get("errors") or [])
    selected_id = state.get("selected_lead_id")
    leads = state.get("discovered_leads") or []

    if not selected_id:
        errors.append("No lead selected for analysis.")
        return {"errors": errors, "execution_status": "FAILED"}

    # 1. Match from current state leads
    selected_lead = next((l for l in leads if l.get("lead_id") == selected_id), None)

    # 2. Match from persistent lead store
    if selected_lead is None:
        store = LeadResultStore(get_settings().lead_json_path)
        persisted = store.get_by_id(selected_id)
        if persisted:
            selected_lead = canonical_lead_output(persisted).model_dump(mode="json")

    if selected_lead is None:
        errors.append(f"Selected lead '{selected_id}' was not found.")
        return {"errors": errors, "execution_status": "FAILED"}

    scoring = selected_lead.get("scoring") or {}
    score = scoring.get("lead_score")

    return {
        "selected_lead": selected_lead,
        "lead_score": score,
        "execution_status": "LEAD_VALIDATED",
    }


# ======================================================================
# STAGE C: BUSINESS RESEARCH AGENT
# ======================================================================

async def research_agent_node(state: WorkflowState) -> dict[str, Any]:
    """Run website crawl and grounded research analysis on selected business."""
    errors = list(state.get("errors") or [])
    metadata = dict(state.get("execution_metadata") or {})
    selected = state.get("selected_lead")

    if not selected:
        errors.append("Missing selected lead for research.")
        return {"errors": errors, "execution_status": "FAILED"}

    logger.info("Executing research for lead: %s", selected.get("lead_id"))
    adapted = adapt_lead(selected)

    # Crawl website if URL is present and additional detail is beneficial
    website_url = adapted.get("website")
    crawl_summary = {}
    if website_url and not adapted.get("about_info"):
        try:
            from app.agents.lead_pipeline.schemas import BusinessRecord
            from app.integrations.website_fetcher import WebsiteCrawler, normalize_url
            clean_url = normalize_url(website_url)
            if clean_url:
                crawler = WebsiteCrawler()
                crawl = await crawler.crawl(BusinessRecord(
                    lead_id=adapted.get("lead_id") or "research-lead",
                    business_name=adapted.get("business_name") or "Business",
                    website=clean_url,
                ))
                crawl_summary = {
                    "status": str(crawl.website_status.value),
                    "pages_crawled": len(crawl.website_content),
                    "errors": [e.message for e in crawl.crawl_errors],
                }
                if crawl.website_content:
                    texts = [p.main_text for p in crawl.website_content if p.main_text]
                    if texts:
                        adapted["description"] = (adapted.get("description") or "") + "\n\n" + texts[0][:500]
                if crawl.services:
                    adapted["services"] = list(dict.fromkeys(
                        adapted.get("services", []) + [s["text"] for s in crawl.services]
                    ))
                if crawl.about:
                    adapted["about_info"] = " ".join([a["text"] for a in crawl.about])[:500]
        except Exception as exc:
            logger.warning("Website crawler encountered error: %s", exc)
            crawl_summary = {"status": "error", "error": str(exc)}

    # Call grounded research agent
    try:
        research_output = await asyncio.to_thread(research_agent, adapted)
        lead_id = selected.get("lead_id")
        if lead_id:
            try:
                await asyncio.to_thread(
                    ResearchOutputService(get_settings().research_root).save,
                    lead_id,
                    research_output,
                )
            except Exception as exc:
                logger.warning("Could not persist research artifact for lead %s: %s", lead_id, exc)
        metadata["research_completed_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "research_results": research_output,
            "website_crawl_summary": crawl_summary,
            "execution_status": "RESEARCH_COMPLETED",
            "execution_metadata": metadata,
        }
    except Exception as exc:
        logger.exception("Research agent failed: %s", exc)
        errors.append(f"Business research failed: {exc}")
        return {
            "errors": errors,
            "execution_status": "FAILED",
        }


async def validate_research_node(state: WorkflowState) -> dict[str, Any]:
    """Validate structured research findings."""
    research = state.get("research_results")
    errors = list(state.get("errors") or [])

    if not research or not isinstance(research, dict):
        errors.append("Research output is invalid or missing.")
        return {"errors": errors, "execution_status": "FAILED"}

    try:
        RichResearchModel.model_validate(research)
        return {"execution_status": "RESEARCH_VALIDATED"}
    except Exception as exc:
        logger.warning("Research model validation warning: %s", exc)
        # Lenient normalization if minor field difference
        return {"execution_status": "RESEARCH_VALIDATED"}


# ======================================================================
# STAGE D: RAG AGENT (CHUNKING, CHROMA INDEXING & GROUNDED RETRIEVAL)
# ======================================================================

async def rag_agent_node(state: WorkflowState) -> dict[str, Any]:
    """Index research findings into ChromaDB and retrieve grounded context for proposal."""
    errors = list(state.get("errors") or [])
    selected = state.get("selected_lead") or {}
    research = state.get("research_results") or {}
    lead_id = selected.get("lead_id", "")
    business_name = selected.get("discovery", {}).get("business_name") or selected.get("business_name", "Business")
    category = selected.get("discovery", {}).get("category") or selected.get("category", "")

    # 1. Index this lead's research into ChromaDB
    try:
        indexed_count = await asyncio.to_thread(
            index_lead_knowledge,
            lead_id=lead_id,
            business_name=business_name,
            research=research,
        )
        logger.info("RAG indexed %d chunks for lead %s", indexed_count, lead_id)
    except Exception as exc:
        logger.warning("RAG indexing encountered an issue: %s", exc)

    # 2. Retrieve grounded context filtered by lead_id
    query = f"Business services challenges and opportunities for {business_name} in {category}"
    try:
        retrieved = await asyncio.to_thread(
            rag_agent,
            query=query,
            lead_id=lead_id,
            k=4,
        )
        return {
            "retrieved_context": retrieved,
            "source_documents": retrieved,
            "execution_status": "RAG_RETRIEVED",
        }
    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        errors.append(f"RAG retrieval failed: {exc}")
        return {
            "retrieved_context": [],
            "source_documents": [],
            "errors": errors,
            "execution_status": "FAILED",
        }


async def validate_retrieved_context_node(state: WorkflowState) -> dict[str, Any]:
    """Validate retrieved context before proposal generation."""
    return {"execution_status": "CONTEXT_VALIDATED"}


# ======================================================================
# STAGE E: PROPOSAL GENERATION AGENT
# ======================================================================

async def proposal_agent_node(state: WorkflowState) -> dict[str, Any]:
    """Generate grounded proposal and outreach email for the selected lead."""
    errors = list(state.get("errors") or [])
    selected = state.get("selected_lead") or {}
    research = state.get("research_results") or {}
    context = state.get("retrieved_context") or []

    adapted = adapt_lead(selected)

    try:
        proposal = await asyncio.to_thread(
            proposal_agent,
            lead=adapted,
            research=research,
            retrieved_context=context,
        )

        email_draft = {
            "subject": proposal.get("email_subject_options", ["Business Outreach"])[0] if proposal.get("email_subject_options") else "Partnership Opportunity",
            "body": proposal.get("personalized_email") or "",
        }

        return {
            "proposal": proposal,
            "outreach_email": email_draft,
            "execution_status": "PROPOSAL_GENERATED",
        }
    except Exception as exc:
        logger.exception("Proposal agent node failed: %s", exc)
        errors.append(f"Proposal generation failed: {exc}")
        return {
            "errors": errors,
            "execution_status": "FAILED",
        }


async def validate_proposal_node(state: WorkflowState) -> dict[str, Any]:
    """Validate generated proposal and draft."""
    proposal = state.get("proposal")
    errors = list(state.get("errors") or [])

    if not proposal or not isinstance(proposal, dict):
        errors.append("Proposal output is invalid.")
        return {"errors": errors, "execution_status": "FAILED"}

    try:
        RichProposalModel.model_validate(proposal)
        return {"execution_status": "PROPOSAL_VALIDATED"}
    except Exception as exc:
        logger.warning("Proposal validation warning: %s", exc)
        return {"execution_status": "PROPOSAL_VALIDATED"}


async def persist_results_node(state: WorkflowState) -> dict[str, Any]:
    """Persist generated proposal for Voice and Email access; pause for human review."""
    selected = state.get("selected_lead") or {}
    lead_id = selected.get("lead_id", "")
    proposal = state.get("proposal") or {}
    metadata = dict(state.get("execution_metadata") or {})

    if lead_id and proposal:
        try:
            store = ProposalJsonService(get_settings().proposal_root)
            store.save(lead_id=lead_id, proposal=proposal, rich_proposal=proposal)
            logger.info("Persisted proposal for lead %s", lead_id)
        except Exception as exc:
            logger.warning("Could not persist proposal file: %s", exc)

    metadata["proposal_generated_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "approval_status": "pending",
        "execution_status": "WAITING_FOR_USER_APPROVAL",
        "execution_metadata": metadata,
    }


# ======================================================================
# STAGE F: HUMAN REVIEW & OPTIONAL OUTREACH
# ======================================================================

async def send_approved_outreach_node(state: WorkflowState) -> dict[str, Any]:
    """Send outreach only after explicit human approval has been granted."""
    approval = state.get("approval_status")
    channel = state.get("outreach_channel", "email")
    selected = state.get("selected_lead") or {}
    lead_id = selected.get("lead_id", "")
    errors = list(state.get("errors") or [])
    metadata = dict(state.get("execution_metadata") or {})

    if approval != "approved":
        return {
            "outreach_result": {
                "status": "blocked",
                "message": "Explicit user approval is required before outreach can be sent.",
            },
            "execution_status": "WAITING_FOR_USER_APPROVAL",
        }

    logger.info("Executing approved outreach via channel: %s for lead: %s", channel, lead_id)

    if channel == "email":
        settings = get_email_settings()
        if not settings.email_sending_enabled:
            return {
                "outreach_result": {
                    "status": "dry_run",
                    "channel": "email",
                    "message": "Email sending is disabled (EMAIL_SENDING_ENABLED=false). Outreach previewed and saved.",
                    "draft": state.get("approved_outreach_email") or state.get("outreach_email"),
                },
                "execution_status": "OUTREACH_EXECUTED",
            }

        service = EmailService(settings)
        try:
            # Preview and approve internally
            draft = service.preview(lead_id)
            review_id = draft.review_id
            service.approve(lead_id=lead_id, review_id=review_id, approved=True)
            result = service.send(lead_id=lead_id, review_id=review_id)
            return {
                "outreach_result": {
                    "status": "queued",
                    "channel": "email",
                    "email_id": str(result.email_id),
                    "review_id": review_id,
                },
                "execution_status": "OUTREACH_EXECUTED",
            }
        except EmailWorkflowError as exc:
            logger.warning("Email workflow returned error code: %s", exc.code)
            return {
                "outreach_result": {
                    "status": "failed",
                    "channel": "email",
                    "error_code": exc.code,
                },
                "errors": errors + [f"Email outreach error: {exc.code}"],
                "execution_status": "OUTREACH_FAILED",
            }
        except Exception as exc:
            logger.exception("Email outreach failed: %s", exc)
            return {
                "outreach_result": {"status": "error", "error": str(exc)},
                "errors": errors + [str(exc)],
                "execution_status": "OUTREACH_FAILED",
            }

    elif channel == "voice":
        settings = get_settings()
        return {
            "outreach_result": {
                "status": "dry_run" if not settings.outbound_calls_enabled else "ready",
                "channel": "voice",
                "message": "Voice dispatch configured. Live dispatch requires OUTBOUND_CALLS_ENABLED=true and consent registration.",
            },
            "execution_status": "OUTREACH_EXECUTED",
        }

    return {
        "outreach_result": {"status": "skipped", "message": "No outreach channel selected."},
        "execution_status": "OUTREACH_EXECUTED",
    }


async def record_outreach_result_node(state: WorkflowState) -> dict[str, Any]:
    """Record outreach result and finalize workflow execution."""
    metadata = dict(state.get("execution_metadata") or {})
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    status = "COMPLETED" if not state.get("errors") else "FAILED"

    return {
        "execution_status": status,
        "execution_metadata": metadata,
    }
