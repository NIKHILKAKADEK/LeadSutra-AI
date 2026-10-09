"""Authenticated consent and eligibility endpoints."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.models.leads import LeadFileError, normalize_indian_mobile
from app.schemas.calling_eligibility import (
    ConsentRecordInput,
    ConsentStatusResponse,
    EligibilityResponse,
    utc_now,
)
from app.services.calling_eligibility import (
    CallingEligibilityStore,
    evaluate_eligibility,
)
from app.services.leads import LeadJsonService

router = APIRouter(
    prefix="/calling-eligibility",
    tags=["calling-eligibility"],
)
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="LeadSutraBearer",
)


def _principal(
    credentials: HTTPAuthorizationCredentials | None,
    required_role: str,
) -> str:
    settings = get_settings()
    expected = (
        settings.eligibility_admin_token
        if required_role == "admin"
        else settings.eligibility_reviewer_token
        or settings.eligibility_admin_token
    )

    if not expected or len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calling eligibility authentication is not securely configured.",
        )

    token = (
        credentials.credentials
        if credentials and credentials.scheme.casefold() == "bearer"
        else ""
    )

    # Administrators retain read access when a separate reviewer is configured.
    admin_token = settings.eligibility_admin_token
    matches_admin = bool(
        required_role == "reviewer"
        and token
        and admin_token
        and len(admin_token) >= 32
        and hmac.compare_digest(token.encode("utf-8"), admin_token.encode("utf-8"))
    )

    if not token or not (
        hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
        or matches_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return (
        "eligibility-admin"
        if required_role == "admin" or matches_admin
        else "eligibility-reviewer"
    )


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    return _principal(credentials, "admin")


def require_reviewer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    return _principal(credentials, "reviewer")


def _store() -> CallingEligibilityStore:
    return CallingEligibilityStore(get_settings().eligibility_db_path)


def _normalize(phone: str) -> str:
    try:
        return normalize_indian_mobile(phone)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Phone number is invalid.",
        ) from None


def _lead_exists(lead_id: str, phone: str) -> bool:
    try:
        leads = LeadJsonService(get_settings().lead_json_path).load()
    except LeadFileError:
        raise HTTPException(
            status_code=503,
            detail="Lead source is unavailable.",
        ) from None

    normalized = _normalize(phone)
    lead = next((item for item in leads if item.lead_id == lead_id), None)

    return bool(
        lead
        and normalized in {
            item.normalized_value for item in lead.phone_numbers
        }
    )


@router.put("/consent", response_model=ConsentStatusResponse)
def record_consent(
    payload: ConsentRecordInput,
    principal: str = Depends(require_admin),
) -> ConsentStatusResponse:
    normalized = _normalize(payload.phone_number)

    if not _lead_exists(payload.lead_id, normalized):
        raise HTTPException(
            status_code=404,
            detail="Lead and phone number were not found together.",
        )

    changes = {"recorded_at": utc_now()}

    if payload.consent_status.value == "verified":
        changes.update({
            "verified_by": principal,
            "verified_at": utc_now(),
        })

    payload = payload.model_copy(update=changes)
    _store().save_consent(payload)

    return review_consent(payload.lead_id, normalized)


@router.get(
    "/consent/{lead_id}",
    response_model=ConsentStatusResponse,
    dependencies=[Depends(require_admin)],
)
def review_consent(
    lead_id: str,
    phone_number: str,
) -> ConsentStatusResponse:
    phone = _normalize(phone_number)
    record = _store().get_consent(lead_id, phone)

    if record is None:
        return ConsentStatusResponse(
            lead_id=lead_id,
            phone_number=phone,
            consent_status="unknown",
            consent_scope=None,
            consent_source=None,
            recorded_at=None,
            verified_at=None,
            verified_by=None,
            expiry_at=None,
            revoked_at=None,
        )

    return ConsentStatusResponse(
        lead_id=lead_id,
        phone_number=phone,
        consent_status=record["consent_status"],
        consent_scope=record["consent_scope"],
        consent_source=record["consent_source"],
        recorded_at=record["recorded_at"],
        verified_at=record["verified_at"],
        verified_by=record["verified_by"],
        expiry_at=record["expiry_at"],
        revoked_at=record["revoked_at"],
    )


@router.get(
    "/{lead_id}",
    response_model=EligibilityResponse,
    dependencies=[Depends(require_reviewer)],
    summary="Preview a lead's calling eligibility",
    description=(
        "Uses the backend-configured outbound purpose and the shared "
        "fail-closed eligibility evaluator. No call is initiated."
    ),
)
def preview_eligibility(
    lead_id: str,
    phone_number: str,
) -> EligibilityResponse:
    try:
        leads = LeadJsonService(get_settings().lead_json_path).load()
    except LeadFileError:
        raise HTTPException(
            status_code=503,
            detail="Lead source is unavailable.",
        ) from None

    phone = _normalize(phone_number)
    store = _store()

    result = evaluate_eligibility(
        lead_id=lead_id,
        phone_number=phone,
        leads=leads,
        store=store,
        purpose=get_settings().outbound_call_purpose,
    )
    return result
