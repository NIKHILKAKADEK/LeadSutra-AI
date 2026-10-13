"""Conditional edge functions and routers for LangGraph orchestration."""
from __future__ import annotations

from typing import Literal

from langgraph.graph import END

from app.graph.state import WorkflowState


def check_query_valid(state: WorkflowState) -> Literal["lead_discovery", "__end__"]:
    """Route after query validation."""
    if state.get("execution_status") == "FAILED" or state.get("errors"):
        return END
    return "lead_discovery"


def check_discovery_success(state: WorkflowState) -> Literal["normalize_and_deduplicate_leads", "__end__"]:
    """Route after lead discovery."""
    if state.get("execution_status") == "FAILED":
        return END
    return "normalize_and_deduplicate_leads"


def check_lead_selected(state: WorkflowState) -> Literal["research_agent", "__end__"]:
    """Route after lead selection validation."""
    if state.get("execution_status") == "FAILED" or not state.get("selected_lead"):
        return END
    return "research_agent"


def check_research_success(state: WorkflowState) -> Literal["validate_research", "__end__"]:
    """Route after business research."""
    if state.get("execution_status") == "FAILED":
        return END
    return "validate_research"


def check_rag_success(state: WorkflowState) -> Literal["validate_retrieved_context", "__end__"]:
    """Route after RAG retrieval."""
    if state.get("execution_status") == "FAILED":
        return END
    return "validate_retrieved_context"


def check_proposal_success(state: WorkflowState) -> Literal["validate_proposal", "__end__"]:
    """Route after proposal generation."""
    if state.get("execution_status") == "FAILED":
        return END
    return "validate_proposal"


def check_approval_for_outreach(state: WorkflowState) -> Literal["send_approved_outreach", "__end__"]:
    """Route after user approval gate; only explicit approval triggers outreach."""
    if state.get("approval_status") == "approved":
        return "send_approved_outreach"
    return END
