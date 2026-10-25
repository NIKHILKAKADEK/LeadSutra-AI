from uuid import UUID

from pydantic import ValidationError
from pymongo.errors import PyMongoError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.auth import get_current_user
from app.agents.email.schema import (
    EmailApprovalRequest, EmailDraft, EmailRequest, EmailResult,
    EmailStatus, EmailHistoryItem, EmailHistoryPage,
)
from app.services.email_service import EmailService, EmailWorkflowError, get_email_service


router = APIRouter(prefix="/emails", tags=["Email"])


def _error(exc: EmailWorkflowError) -> HTTPException:
    detail = {"code": exc.code}
    if exc.email_id is not None:
        detail["email_id"] = str(exc.email_id)
    return HTTPException(status_code=exc.status_code, detail=detail)


@router.post("/preview", response_model=EmailDraft)
def preview(request: EmailRequest, service: EmailService = Depends(get_email_service)):
    try:
        return service.preview(
            request.lead_id, template=request.template, regenerate=request.regenerate,
            research_if_missing=request.research_if_missing,
        )
    except EmailWorkflowError as exc:
        raise _error(exc) from None


@router.put("/approval", response_model=EmailDraft)
def approve(request: EmailApprovalRequest, user: dict = Depends(get_current_user),
            service: EmailService = Depends(get_email_service)):
    try:
        principal = user.get("email") or user.get("_id")
        if not isinstance(principal, str) or not principal:
            raise HTTPException(status_code=401, detail="Authenticated user identity is invalid.")
        return service.approve(
            request.lead_id, request.review_id, request.approved, principal,
            template=request.template, subject=request.subject, body=request.body,
        )
    except EmailWorkflowError as exc:
        raise _error(exc) from None


@router.post("/send", response_model=EmailResult, status_code=202)
def send(request: EmailRequest, background: BackgroundTasks, service: EmailService = Depends(get_email_service)):
    try:
        result, created = service.queue(request.lead_id, request.draft_key)
    except EmailWorkflowError as exc:
        raise _error(exc) from None
    if created:
        background.add_task(service.send, result.email_id)
    return result


@router.get(
    "", response_model=EmailHistoryPage, summary="List email history",
    description=(
        "Read stored email results, newest created_at first with email_id as a tie-breaker. "
        "pending and sending are in progress; sent means SMTP acceptance, not verified delivery. "
        "failed and uncertain retain their existing meanings. Raw error details are omitted."
    ),
)
def list_email_history(
    status: EmailStatus | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    service: EmailService = Depends(get_email_service),
) -> EmailHistoryPage:
    try:
        records, total = service.store.list_records(status=status, limit=limit, offset=offset)
    except (PyMongoError, RuntimeError, OSError, ValidationError):
        raise HTTPException(status_code=503, detail={"code": "email_history_unavailable"}) from None
    return EmailHistoryPage(
        emails=[EmailHistoryItem.model_validate(record.model_dump()) for record in records],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{email_id}", response_model=EmailResult)
def result(email_id: UUID, service: EmailService = Depends(get_email_service)):
    try:
        return service.result(email_id)
    except EmailWorkflowError as exc:
        raise _error(exc) from None
