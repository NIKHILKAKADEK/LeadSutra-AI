"""Independent, outreach-focused proposal generation endpoint."""

import logging

from fastapi import APIRouter, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.agents.lead_pipeline.schemas import LeadResult
from app.models.proposal import ProposalResult
from app.schemas.ai_agents import ProposalGenerationRequest, ProposalGenerationResponse
from app.services.ai_agents import create_outreach_proposal, resolve_lead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/proposals", tags=["Proposal"])


@router.post("/generate")
async def generate_proposal(
    payload: LeadResult | ProposalGenerationRequest,
) -> ProposalGenerationResponse:
    """Generate outreach material without invoking research or RAG.

    Research and retrieved context are optional caller-supplied inputs.
    """
    try:
        if isinstance(payload, LeadResult):
            lead = payload
            research = None
            retrieved_context = None
        else:
            lead = resolve_lead(payload.lead, payload.lead_id)
            research = payload.research.model_dump() if payload.research else None
            retrieved_context = payload.retrieved_context

        proposal = await run_in_threadpool(
            create_outreach_proposal,
            lead,
            research=research,
            retrieved_context=retrieved_context,
        )
        validated = ProposalResult.model_validate(proposal)
        return ProposalGenerationResponse(
            success=True,
            lead_id=lead.lead_id,
            business_name=lead.discovery.business_name,
            proposal=validated,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, UnicodeError):
        raise HTTPException(status_code=503, detail="Saved lead source is unavailable.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("Outreach proposal agent failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Outreach proposal generation failed.",
        ) from None
