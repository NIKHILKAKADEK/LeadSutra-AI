"""Independent business research agent endpoint."""

import logging

from fastapi import APIRouter, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.agents.lead_pipeline.schemas import LeadResult
from app.models.research import ResearchResult
from app.schemas.ai_agents import LeadAgentRequest, LeadDiscoverySelection
from app.services.ai_agents import analyze_lead, resolve_lead

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
