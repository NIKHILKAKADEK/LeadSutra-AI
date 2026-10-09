"""Versioned API router for implemented backend capabilities."""

from fastapi import APIRouter, HTTPException, status

from app.api.v1.leads import router as discovery_router
from app.api.v1.calling_eligibility import router as calling_eligibility_router
from app.api.v1.calls import router as outbound_calls_router
from app.api.v1.emails import router as emails_router
from app.core.config import get_settings
from app.integrations.omnidimension import (
    OmniDimensionConnectionError,
    OmniDimensionCredentialsMissingError,
    OmniDimensionService,
)

api_router = APIRouter()


@api_router.get("/", tags=["api"])
def api_root() -> dict[str, str]:
    """Return basic metadata for the versioned API."""
    return {
        "version": get_settings().api_version,
        "status": "available",
    }


@api_router.get(
    "/integrations/omnidimension/connection",
    tags=["integrations"],
)
def check_omnidimension_connection() -> dict[str, str]:
    """Check OmniDimension API connectivity without exposing provider data."""
    service = OmniDimensionService(get_settings().omnidim_api_key)

    try:
        service.verify_connection()
    except OmniDimensionCredentialsMissingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unavailable",
                "provider": "omnidimension",
                "message": "OmniDimension API key is not configured.",
            },
        ) from None
    except OmniDimensionConnectionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "status": "error",
                "provider": "omnidimension",
                "message": "OmniDimension connection check failed.",
            },
        ) from None

    return {
        "status": "connected",
        "provider": "omnidimension",
    }


api_router.include_router(discovery_router)
api_router.include_router(calling_eligibility_router)
api_router.include_router(outbound_calls_router)
api_router.include_router(emails_router)
