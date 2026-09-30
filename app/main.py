"""LeadSutra AI FastAPI Application Backend."""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.db.repositories.lead_repository import default_lead_repository
from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead
from app.services.lead_discovery.search_service import (
    search_and_extract_business_profiles,
    search_enrich_score_and_persist_leads,
)

app = FastAPI(
    title="LeadSutra AI — Backend API",
    description="AI-powered SDR platform for business discovery, scraping, contact extraction, and lead scoring.",
    version="1.0.0",
)


class SearchRequest(BaseModel):
    query: str
    location: str
    limit: Optional[int] = 10
    deduplicate: Optional[bool] = True
    enrich_websites: Optional[bool] = True
    extract_contacts: Optional[bool] = True
    score_leads: Optional[bool] = True
    persist: Optional[bool] = True


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "online",
        "app": "LeadSutra AI",
        "docs": "/docs",
    }


@app.post("/api/search", response_model=Dict[str, Any])
async def search_and_process_leads(request: SearchRequest):
    """
    Execute full LeadSutra pipeline:
    Search (Google -> Foursquare failover) -> Deduplication -> Website Scraping -> Contact Extraction -> Lead Scoring -> MongoDB.
    """
    try:
        if request.persist:
            leads, profiles = await search_enrich_score_and_persist_leads(
                query=request.query,
                location=request.location,
                limit=request.limit,
                deduplicate=request.deduplicate,
                enrich_websites=request.enrich_websites,
                extract_contacts=request.extract_contacts,
                score_leads=request.score_leads,
            )
        else:
            leads, profiles = await search_and_extract_business_profiles(
                query=request.query,
                location=request.location,
                limit=request.limit,
                deduplicate=request.deduplicate,
                enrich_websites=request.enrich_websites,
                extract_contacts=request.extract_contacts,
            )

        return {
            "query": request.query,
            "location": request.location,
            "total_results": len(leads),
            "leads": [l.to_dict() for l in leads],
            "profiles": [p.to_dict() for p in profiles],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/leads", response_model=List[Dict[str, Any]])
async def get_stored_leads(
    min_score: int = Query(default=0, ge=0, le=100),
    priority: Optional[str] = Query(default=None, pattern="^(high|medium|low)$"),
    limit: int = Query(default=50, ge=1, le=100),
):
    """Retrieve scored leads from database filtered by score or priority."""
    try:
        leads = await default_lead_repository.get_scored_leads(min_score=min_score, priority=priority)
        return [l.to_dict() for l in leads[:limit]]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/leads/{external_place_id}", response_model=Dict[str, Any])
async def get_lead_details(external_place_id: str, source: str = "google"):
    """Retrieve details of a single lead and its linked BusinessProfile."""
    lead = await default_lead_repository.find_by_external_id(external_place_id, source)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    profile = await default_lead_repository.find_profile_by_lead_id(external_place_id)
    return {
        "lead": lead.to_dict(),
        "profile": profile.to_dict() if profile else None,
    }
