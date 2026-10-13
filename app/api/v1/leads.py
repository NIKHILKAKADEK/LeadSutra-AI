"""HTTP interface for the existing lead discovery pipeline."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.agents.lead_pipeline.schemas import LeadDiscoveryRequest, LeadDiscoveryResponse, StoredLeadPage
from app.api.v1.calling_eligibility import require_reviewer
from app.core.config import get_settings
from app.services.lead_results import LeadResultStore
from app.agents.lead_pipeline.pipeline import canonical_lead_output

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["Lead Discovery"])


@router.get(
    "", response_model=StoredLeadPage, dependencies=[Depends(require_reviewer)],
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
            q=q, category=category, qualification_status=qualification_status,
            priority=priority, limit=limit, offset=offset,
        )
    except (OSError, UnicodeError, ValueError):
        raise HTTPException(status_code=503, detail="Lead source is unavailable.") from None
    return StoredLeadPage(items=records, total=total, limit=limit, offset=offset)


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
