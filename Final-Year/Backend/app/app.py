from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .api.router import api_router
from .agents.lead_pipeline.pipeline import LeadPipeline
from .core.config import get_settings
from .database.mongodb import close_mongo_database, get_mongo_database


logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log_path = Path(get_settings().log_file_path)
log_path.parent.mkdir(parents=True, exist_ok=True)
file_handler = RotatingFileHandler(
    log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
))
logging.getLogger().addHandler(file_handler)

logger = logging.getLogger("leadsutra.api")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LeadSutra AI API")

    database = get_mongo_database()
    try:
        if database is None:
            raise RuntimeError("MONGODB_URI is required; MongoDB-backed storage is mandatory.")
        if get_settings().auth_jwt_secret is None or len(
            get_settings().auth_jwt_secret.get_secret_value()
        ) < 32:
            raise RuntimeError("AUTH_JWT_SECRET must be configured with at least 32 characters.")
        database.connect()
        app.state.mongodb_enabled = True

        # One application-level service instance.
        app.state.lead_discovery_service = LeadPipeline()
        logger.info("Lead discovery service initialized")
        yield
    finally:
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
        close_mongo_database()


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in get_settings().cors_allowed_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api", include_in_schema=False)


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
    database = get_mongo_database()
    return {
        "status": "healthy",
        "service": "leadsutra-api",
        "database": "connected" if database and database.connected else (
            "disabled" if database is None else "disconnected"
        ),
    }

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
