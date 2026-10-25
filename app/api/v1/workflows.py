"""API endpoints for LangGraph orchestrator workflows."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.graph.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["Workflows"])


class WorkflowStartRequest(BaseModel):
    query: str = Field(min_length=1, max_length=256, description="Search query or natural language phrase")
    location: str | None = Field(default=None, description="Optional city or geographic area")
    limit: int = Field(default=10, ge=1, le=50)
    priority: Literal["High", "Medium", "Low"] | None = None


class LeadSelectionRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=256, description="ID of the discovered lead to research")


class ProposalApprovalRequest(BaseModel):
    approved: bool = Field(default=True, description="Whether the proposal is approved for outreach")
    edited_proposal: dict[str, Any] | None = None
    edited_email: dict[str, Any] | None = None


class OutreachTriggerRequest(BaseModel):
    channel: Literal["email", "voice"] = "email"
    confirm_approved: bool = Field(default=True, description="Explicit human confirmation for outreach")


@router.post("", summary="Start a new LangGraph sales discovery workflow")
async def start_workflow(payload: WorkflowStartRequest) -> dict[str, Any]:
    orch = get_orchestrator()
    state = await orch.start_discovery(
        query=payload.query,
        location=payload.location,
        limit=payload.limit,
        priority=payload.priority,
    )
    if state.get("errors") and state.get("execution_status") == "FAILED":
        raise HTTPException(status_code=400, detail={"errors": state.get("errors")})

    return {
        "workflow_id": state.get("workflow_id"),
        "execution_status": state.get("execution_status"),
        "business_category": state.get("business_category"),
        "search_location": state.get("search_location"),
        "discovered_leads": state.get("discovered_leads", []),
        "candidates_count": state.get("candidates_count", 0),
        "execution_metadata": state.get("execution_metadata", {}),
    }


@router.get("", summary="List persisted workflows")
def list_workflows(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    orch = get_orchestrator()
    items = orch.list_workflows(limit=limit, offset=offset)
    return {"workflows": items, "total": len(items), "limit": limit, "offset": offset}


@router.get("/{workflow_id}", summary="Get full workflow state")
def get_workflow_state(workflow_id: str) -> dict[str, Any]:
    orch = get_orchestrator()
    state = orch.get_workflow(workflow_id)
    if not state:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return state


@router.get("/{workflow_id}/results", summary="Get structured workflow results")
def get_workflow_results(workflow_id: str) -> dict[str, Any]:
    orch = get_orchestrator()
    state = orch.get_workflow(workflow_id)
    if not state:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    return {
        "workflow_id": workflow_id,
        "execution_status": state.get("execution_status"),
        "selected_lead": state.get("selected_lead"),
        "research_results": state.get("research_results"),
        "retrieved_context": state.get("retrieved_context"),
        "proposal": state.get("proposal"),
        "outreach_email": state.get("outreach_email"),
        "approval_status": state.get("approval_status"),
        "outreach_result": state.get("outreach_result"),
        "errors": state.get("errors", []),
    }


@router.post("/{workflow_id}/select", summary="Select a lead and resume research, RAG, and proposal")
async def select_lead_and_run(
    workflow_id: str,
    payload: LeadSelectionRequest,
) -> dict[str, Any]:
    orch = get_orchestrator()
    try:
        state = await orch.select_lead_and_resume(
            workflow_id=workflow_id,
            lead_id=payload.lead_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error resuming workflow with selected lead: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "workflow_id": workflow_id,
        "execution_status": state.get("execution_status"),
        "selected_lead_id": state.get("selected_lead_id"),
        "research_results": state.get("research_results"),
        "retrieved_context": state.get("retrieved_context"),
        "proposal": state.get("proposal"),
        "outreach_email": state.get("outreach_email"),
        "approval_status": state.get("approval_status"),
        "errors": state.get("errors", []),
    }


@router.post("/{workflow_id}/approve", summary="Review and approve proposal")
async def approve_proposal(
    workflow_id: str,
    payload: ProposalApprovalRequest,
) -> dict[str, Any]:
    orch = get_orchestrator()
    state = orch.get_workflow(workflow_id)
    if not state:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if not payload.approved:
        state["approval_status"] = "rejected"
        orch._save_workflow(workflow_id, state)
        return {"workflow_id": workflow_id, "approval_status": "rejected"}

    state["approval_status"] = "approved"
    if payload.edited_proposal:
        state["approved_proposal"] = payload.edited_proposal
    if payload.edited_email:
        state["approved_outreach_email"] = payload.edited_email

    orch._save_workflow(workflow_id, state)
    return {
        "workflow_id": workflow_id,
        "approval_status": "approved",
        "message": "Proposal approved. Ready for outreach authorization.",
    }


@router.post("/{workflow_id}/outreach", summary="Explicitly authorize and execute outreach")
async def trigger_outreach(
    workflow_id: str,
    payload: OutreachTriggerRequest,
) -> dict[str, Any]:
    if not payload.confirm_approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Outreach requires confirm_approved=True.",
        )

    orch = get_orchestrator()
    try:
        state = await orch.approve_and_send_outreach(
            workflow_id=workflow_id,
            channel=payload.channel,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error executing outreach for workflow %s: %s", workflow_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "workflow_id": workflow_id,
        "execution_status": state.get("execution_status"),
        "outreach_channel": payload.channel,
        "outreach_result": state.get("outreach_result"),
        "errors": state.get("errors", []),
    }
