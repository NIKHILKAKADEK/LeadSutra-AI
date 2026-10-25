from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .api.router import api_router
from .agents.lead_pipeline.pipeline import LeadPipeline


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("leadsutra.api")
STATIC_DIR = Path(__file__).resolve().parent / "static"


# ============================================================
# APPLICATION LIFECYCLE
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LeadSutra AI API")

    # One application-level service instance.
    app.state.lead_discovery_service = LeadPipeline()

    logger.info("Lead discovery service initialized")

    yield

    logger.info("Shutting down LeadSutra AI API")

    # Allow the service to clean up resources if it provides cleanup.
    service = getattr(app.state, "lead_discovery_service", None)

    if service is not None:
        close_method = getattr(service, "close", None)

        if close_method is not None:
            try:
                result = close_method()

                if hasattr(result, "__await__"):
                    await result

            except Exception:
                logger.exception("Error while closing LeadPipeline")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="LeadSutra AI",
    description=(
        "AI-powered autonomous lead discovery, enrichment, "
        "scoring, multi-agent LangGraph orchestration, RAG, and qualification API."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Workflows", "description": "LangGraph multi-agent orchestration for sales pipelines."},
        {"name": "Lead Discovery", "description": "Find, enrich, score, and search saved business leads."},
        {"name": "Business Research", "description": "Run grounded research for a selected lead."},
        {"name": "RAG", "description": "Retrieve relevant knowledge documents for a caller-provided query."},
        {"name": "Proposal", "description": "Generate outreach-ready proposal content for a selected lead."},
        {"name": "Email", "description": "Preview, approve, send, and inspect email outreach."},
        {"name": "Voice", "description": "Check calling eligibility, consent, dispatch calls, and inspect call history."},
    ],
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api", include_in_schema=False)


# ============================================================
# HEALTH & WEB UI
# ============================================================

@app.get("/", tags=["Health"], include_in_schema=False)
async def root(request: Request) -> Any:
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        index_file = STATIC_DIR / "index.html"
        if index_file.is_file():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))

    return {
        "name": "LeadSutra AI",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
        "ui": "/ui",
        "redoc": "/redoc",
    }


@app.get("/ui", include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>LeadSutra AI UI not found</h1>", status_code=404)


@app.get("/health", tags=["Health"], include_in_schema=False)
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "leadsutra-api",
    }


# ============================================================
# LOCAL WINDOWS ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsProactorEventLoopPolicy()
        )

    uvicorn.run(
        "app.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
