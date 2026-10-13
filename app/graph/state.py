"""Typed workflow state for LeadSutra AI LangGraph orchestration."""
from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    # Discovery inputs
    user_query: str
    search_location: str
    business_category: str
    discovery_limit: int
    priority_filter: str | None

    # Stage A: Discovered leads
    discovered_leads: list[dict[str, Any]]
    candidates_count: int

    # Stage B: Lead selection
    selected_lead_id: str | None
    selected_lead: dict[str, Any] | None

    # Stage C: Research
    research_results: dict[str, Any] | None
    website_crawl_summary: dict[str, Any] | None

    # Stage D: RAG
    source_documents: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]

    # Lead scoring
    lead_score: float | None

    # Stage E: Proposal & Email Draft
    proposal: dict[str, Any] | None
    outreach_email: dict[str, Any] | None

    # Stage F: Human review & approval
    approval_status: str  # "pending", "approved", "rejected", "modified"
    approved_proposal: dict[str, Any] | None
    approved_outreach_email: dict[str, Any] | None

    # Outreach execution
    outreach_channel: str  # "email", "voice", "none"
    outreach_result: dict[str, Any] | None

    # Tracking & observability
    execution_status: str  # "START", "DISCOVERED", "WAITING_FOR_SELECTION", "RESEARCHED", "RAG_RETRIEVED", "PROPOSED", "WAITING_FOR_APPROVAL", "COMPLETED", "FAILED"
    errors: list[str]
    execution_metadata: dict[str, Any]
    thread_id: str
    workflow_id: str
