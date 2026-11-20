import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.agents.lead_pipeline.schema import LeadResult
from app.agents.research.schema import (
    LeadAgentRequest,
    LeadDiscoverySelection,
    CompetitorAnalysis,
    ResearchResult,
)
from app.services.ai_agents import (
    analyze_competitors,
    analyze_lead,
    get_competitor_analysis,
    index_research_knowledge,
    resolve_lead,
)
from app.services.lead_results import LeadResultStore
from app.core.config import DiscoverySettings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/research", tags=["Business Research"])


@router.post(
    "/analyze",
    response_model=ResearchResult,
    summary="Research one discovered lead",
    description=(
        "Accepts a single lead record, a `{lead: ...}` object, a saved `{lead_id: ...}`, "
        "or the full lead-discovery response. When that response contains multiple leads, "
        "include its `lead_id` at the top level to select one."
    ),
)
async def analyze_business(
    payload: LeadResult | LeadAgentRequest | LeadDiscoverySelection,
    background_tasks: BackgroundTasks,
) -> ResearchResult:
    try:
        if isinstance(payload, LeadResult):
            lead = payload
        elif isinstance(payload, LeadDiscoverySelection):
            if payload.lead_id:
                lead = next(
                    (item for item in payload.leads if item.lead_id == payload.lead_id),
                    None,
                )
                if lead is None:
                    raise HTTPException(status_code=404, detail="Selected lead was not found in the discovery response.")
            elif len(payload.leads) == 1:
                lead = payload.leads[0]
            else:
                raise HTTPException(
                    status_code=422,
                    detail="This discovery response contains multiple leads. Add the selected lead_id at the top level, or send one lead object.",
                )
        else:
            lead = resolve_lead(payload.lead, payload.lead_id)
        result = await run_in_threadpool(analyze_lead, lead)
        background_tasks.add_task(
            index_research_knowledge,
            lead.lead_id,
            lead.discovery.business_name,
            result,
        )
        return ResearchResult.model_validate(result)
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, UnicodeError):
        raise HTTPException(status_code=503, detail="Saved lead source is unavailable.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("Business research agent failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Business research failed.",
        ) from None


@router.post(
    "/competitors/{lead_id}",
    response_model=CompetitorAnalysis,
    summary="Find nearby businesses in the same category",
)
async def competitor_analysis(
    lead_id: str,
    refresh: bool = Query(False),
) -> CompetitorAnalysis:
    try:
        store = LeadResultStore(get_settings().lead_json_path)
        lead = store.get_by_id(lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="No saved lead was found with that lead_id.")
        if not refresh:
            cached = await run_in_threadpool(get_competitor_analysis, lead_id)
            radius = DiscoverySettings().leadsutra_competitor_radius_meters
            if cached is not None and cached.get("radius_meters") == radius:
                return CompetitorAnalysis.model_validate(cached)
        result = await analyze_competitors(lead)
        return CompetitorAnalysis.model_validate(result)
    except HTTPException:
        raise
    except (OSError, UnicodeError):
        raise HTTPException(status_code=503, detail="Saved lead source is unavailable.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("Competitor analysis failed for lead %s", lead_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitor analysis failed. Check Google Places/Maps configuration and retry.",
        ) from None
