from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
                logger.exception(
                    "Error while closing LeadPipeline"
                )


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="LeadSutra AI",
    description=(
        "AI-powered autonomous lead discovery, enrichment, "
        "scoring and qualification API."
    ),
    version="1.0.0",
    lifespan=lifespan,
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


# ============================================================
# HEALTH
# ============================================================

@app.get("/", tags=["Health"])
async def root() -> dict[str, Any]:
    return {
        "name": "LeadSutra AI",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["Health"])
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
