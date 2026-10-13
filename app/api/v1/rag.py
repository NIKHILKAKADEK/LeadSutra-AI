"""Independent RAG retrieval endpoint."""

import logging

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.schemas.ai_agents import RetrievalRequest
from app.services.ai_agents import retrieve_knowledge

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rag", tags=["RAG"])


@router.post("/retrieve")
async def retrieve(payload: RetrievalRequest) -> dict:
    try:
        documents = await run_in_threadpool(
            retrieve_knowledge, payload.query, payload.k
        )
        return {"query": payload.query, "count": len(documents), "documents": documents}
    except Exception:
        logger.exception("Knowledge retrieval failed")
        raise HTTPException(status_code=502, detail="Knowledge retrieval failed.") from None
