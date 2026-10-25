"""HTTP interface for lead discovery, search, retrieval, and analysis."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.agents.lead_pipeline.pipeline import canonical_lead_output
from app.agents.lead_pipeline.schemas import (
    LeadDiscoveryRequest,
    LeadDiscoveryResponse,
    LeadResult,
    StoredLeadPage,
)
from app.api.v1.calling_eligibility import require_reviewer
from app.core.config import get_settings
from app.graph.orchestrator import get_orchestrator
from app.services.lead_results import LeadResultStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["Lead Discovery"])


class LeadSearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=256, description="Business category or natural query")
    location: str | None = Field(default=None, description="Target city or region")
    limit: int = Field(default=10, ge=1, le=50)
    priority: Literal["High", "Medium", "Low"] | None = None


@router.get(
    "",
    response_model=StoredLeadPage,
    dependencies=[Depends(require_reviewer)],
    summary="Search stored leads",
    description=(
        "Read saved canonical leads without discovery, scraping, enrichment, or scoring. "
        "Newest saved run wins per lead ID; results keep newest-run order. "
        "q is a case-insensitive substring search over name, address, category, phone, "
        "and website. Category is an exact, case-insensitive filter."
    ),
)
def list_stored_leads(
    q: str | None = Query(default=None, min_length=1, max_length=256),
    category: str | None = Query(default=None, min_length=1, max_length=256),
    qualification_status: Literal["Qualified", "Needs Review", "Not Qualified", "Unknown"] | None = Query(default=None),
    priority: Literal["High", "Medium", "Low", "Unknown"] | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> StoredLeadPage:
    try:
        records, total = LeadResultStore(get_settings().lead_json_path).list_records(
            q=q,
            category=category,
            qualification_status=qualification_status,
            priority=priority,
            limit=limit,
            offset=offset,
        )
    except (OSError, UnicodeError, ValueError):
        raise HTTPException(status_code=503, detail="Lead source is unavailable.") from None
    return StoredLeadPage(items=records, total=total, limit=limit, offset=offset)


@router.get(
    "/{lead_id}",
    response_model=LeadResult,
    summary="Get single stored lead by ID",
)
def get_stored_lead(lead_id: str) -> LeadResult:
    try:
        lead = LeadResultStore(get_settings().lead_json_path).get_by_id(lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found.")
        return canonical_lead_output(lead)
    except HTTPException:
        raise
    except (OSError, UnicodeError, ValueError):
        raise HTTPException(status_code=503, detail="Lead source is unavailable.") from None


@router.post(
    "/search",
    summary="Search business leads via LangGraph orchestrator",
)
async def search_leads(payload: LeadSearchQuery) -> dict[str, Any]:
    orch = get_orchestrator()
    state = await orch.start_discovery(
        query=payload.query,
        location=payload.location,
        limit=payload.limit,
        priority=payload.priority,
    )
    if state.get("errors") and state.get("execution_status") == "FAILED":
        raise HTTPException(status_code=400, detail={"errors": state.get("errors")})

    leads = state.get("discovered_leads") or []
    return {
        "success": True,
        "workflow_id": state.get("workflow_id"),
        "status": state.get("execution_status"),
        "query": payload.query,
        "category": state.get("business_category"),
        "location": state.get("search_location"),
        "count": len(leads),
        "leads": leads,
    }


@router.post(
    "/{lead_id}/analyze",
    summary="Analyze a specific lead and generate proposal",
)
async def analyze_lead_by_id(lead_id: str) -> dict[str, Any]:
    orch = get_orchestrator()
    store = LeadResultStore(get_settings().lead_json_path)
    persisted = store.get_by_id(lead_id)
    if not persisted:
        raise HTTPException(status_code=404, detail=f"Lead with ID '{lead_id}' not found.")

    # Start or resume a workflow for this lead
    wf = await orch.start_discovery(
        query=persisted.discovery.category or "business",
        location=persisted.discovery.address or "Unknown",
        limit=1,
    )
    wf_id = wf.get("workflow_id")
    final_state = await orch.select_lead_and_resume(workflow_id=wf_id, lead_id=lead_id)

    return {
        "workflow_id": wf_id,
        "lead_id": lead_id,
        "execution_status": final_state.get("execution_status"),
        "research": final_state.get("research_results"),
        "proposal": final_state.get("proposal"),
        "outreach_email": final_state.get("outreach_email"),
        "approval_status": final_state.get("approval_status"),
        "errors": final_state.get("errors", []),
    }


@router.post("/discover", response_model=LeadDiscoveryResponse)
async def discover_leads(payload: LeadDiscoveryRequest, request: Request) -> LeadDiscoveryResponse:
    query = payload.query.strip()
    location = payload.location.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required.")
    if not location:
        raise HTTPException(status_code=400, detail="Location is required.")

    try:
        result = await request.app.state.lead_discovery_service.run(
            query=query,
            location=location,
            limit=payload.limit,
            mode="full",
            priority=payload.priority,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("LeadSutra pipeline failed")
        raise HTTPException(status_code=500, detail={
            "message": "Lead discovery, enrichment or scoring failed.",
            "error": str(exc),
        }) from exc

    try:
        leads = [canonical_lead_output(lead) for lead in result.leads]
        return LeadDiscoveryResponse(
            success=True,
            query=query,
            location=location,
            count=len(leads),
            source=result.source,
            fallback_used=result.fallback_used,
            leads=leads,
        )
    except Exception as exc:
        logger.exception("Failed to normalize pipeline output")
        raise HTTPException(status_code=500, detail={
            "message": "Invalid pipeline output.",
            "error": str(exc),
        }) from exc
