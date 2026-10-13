"""Central LangGraph Orchestrator for LeadSutra AI multi-agent workflow."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.edges import (
    check_approval_for_outreach,
    check_discovery_success,
    check_lead_selected,
    check_proposal_success,
    check_query_valid,
    check_rag_success,
    check_research_success,
)
from app.graph.nodes import (
    lead_discovery_node,
    normalize_and_deduplicate_leads_node,
    persist_and_return_leads_node,
    persist_results_node,
    proposal_agent_node,
    rag_agent_node,
    record_outreach_result_node,
    research_agent_node,
    send_approved_outreach_node,
    validate_proposal_node,
    validate_query_node,
    validate_retrieved_context_node,
    validate_research_node,
    validate_selected_lead_node,
)
from app.graph.state import WorkflowState

logger = logging.getLogger("leadsutra.orchestrator")
_WORKFLOW_STORAGE_DIR = Path(__file__).resolve().parents[2] / "app" / "results" / "workflows"


# ======================================================================
# PAUSE / GATING NODES
# ======================================================================

async def wait_for_user_selection_node(state: WorkflowState) -> dict[str, Any]:
    """Checkpoint node waiting for user lead selection."""
    if not state.get("selected_lead_id"):
        return {"execution_status": "WAITING_FOR_USER_SELECTION"}
    return {"execution_status": "LEAD_SELECTION_RECEIVED"}


def route_selection_gate(state: WorkflowState):
    """Conditionally pause workflow until user selects a lead."""
    if not state.get("selected_lead_id") or state.get("execution_status") == "WAITING_FOR_USER_SELECTION":
        return END
    return "validate_selected_lead"


async def wait_for_user_approval_node(state: WorkflowState) -> dict[str, Any]:
    """Checkpoint node waiting for user proposal approval."""
    if state.get("approval_status") != "approved":
        return {"execution_status": "WAITING_FOR_USER_APPROVAL"}
    return {"execution_status": "APPROVAL_RECEIVED"}


def route_approval_gate(state: WorkflowState):
    """Conditionally pause workflow until user approves proposal for outreach."""
    if state.get("approval_status") != "approved":
        return END
    return "send_approved_outreach"


def route_workflow_start(state: WorkflowState) -> str:
    """Resume from the last user-controlled checkpoint instead of repeating discovery."""
    if state.get("approval_status") == "approved":
        return "send_approved_outreach"
    if state.get("selected_lead_id"):
        return "validate_selected_lead"
    return "validate_query"


# ======================================================================
# WORKFLOW GRAPH CONSTRUCTION
# ======================================================================

def build_leadsutra_graph() -> StateGraph:
    """Build the compiled LangGraph StateGraph connecting all multi-agent stages."""
    workflow = StateGraph(WorkflowState)

    # Stage A: Query validation and lead discovery
    workflow.add_node("validate_query", validate_query_node)
    workflow.add_node("lead_discovery", lead_discovery_node)
    workflow.add_node("normalize_and_deduplicate_leads", normalize_and_deduplicate_leads_node)
    workflow.add_node("persist_and_return_leads", persist_and_return_leads_node)
    workflow.add_node("wait_for_user_selection", wait_for_user_selection_node)

    # Stage B & C: Lead validation and business research
    workflow.add_node("validate_selected_lead", validate_selected_lead_node)
    workflow.add_node("research_agent", research_agent_node)
    workflow.add_node("validate_research", validate_research_node)

    # Stage D: RAG indexing and retrieval
    workflow.add_node("rag_agent", rag_agent_node)
    workflow.add_node("validate_retrieved_context", validate_retrieved_context_node)

    # Stage E: Proposal generation and persistence
    workflow.add_node("proposal_agent", proposal_agent_node)
    workflow.add_node("validate_proposal", validate_proposal_node)
    workflow.add_node("persist_results", persist_results_node)
    workflow.add_node("wait_for_user_approval", wait_for_user_approval_node)

    # Stage F: Human review and outreach
    workflow.add_node("send_approved_outreach", send_approved_outreach_node)
    workflow.add_node("record_outreach_result", record_outreach_result_node)

    # ---------------- Edges & Conditional Routing ----------------
    workflow.add_conditional_edges(START, route_workflow_start)
    workflow.add_conditional_edges("validate_query", check_query_valid)
    workflow.add_conditional_edges("lead_discovery", check_discovery_success)
    workflow.add_edge("normalize_and_deduplicate_leads", "persist_and_return_leads")
    workflow.add_edge("persist_and_return_leads", "wait_for_user_selection")
    workflow.add_conditional_edges("wait_for_user_selection", route_selection_gate)

    workflow.add_conditional_edges("validate_selected_lead", check_lead_selected)
    workflow.add_conditional_edges("research_agent", check_research_success)
    workflow.add_edge("validate_research", "rag_agent")

    workflow.add_conditional_edges("rag_agent", check_rag_success)
    workflow.add_edge("validate_retrieved_context", "proposal_agent")

    workflow.add_conditional_edges("proposal_agent", check_proposal_success)
    workflow.add_edge("validate_proposal", "persist_results")
    workflow.add_edge("persist_results", "wait_for_user_approval")
    workflow.add_conditional_edges("wait_for_user_approval", route_approval_gate)

    workflow.add_edge("send_approved_outreach", "record_outreach_result")
    workflow.add_edge("record_outreach_result", END)

    return workflow


# ======================================================================
# WORKFLOW PERSISTENCE & CENTRAL ORCHESTRATOR
# ======================================================================

class LeadSutraOrchestrator:
    """Central multi-agent coordinator managing LangGraph execution, checkpointing, and durable persistence."""

    def __init__(self, storage_dir: Path | str | None = None):
        self.storage_dir = Path(storage_dir) if storage_dir else _WORKFLOW_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.checkpointer = MemorySaver()
        self.graph = build_leadsutra_graph().compile(checkpointer=self.checkpointer)

    def _save_workflow(self, workflow_id: str, state: WorkflowState) -> None:
        """Persist workflow state snapshot safely to JSON on disk."""
        path = self.storage_dir / f"{workflow_id}.json"
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            temp.replace(path)
        except Exception as exc:
            logger.warning("Failed to persist workflow %s: %s", workflow_id, exc)

    def get_workflow(self, workflow_id: str) -> WorkflowState | None:
        """Load workflow state by ID from disk or checkpointer."""
        path = self.storage_dir / f"{workflow_id}.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                logger.warning("Error reading workflow file %s: %s", path, exc)
        return None

    def list_workflows(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List summary of saved workflows sorted by modification time."""
        files = sorted(
            self.storage_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        results = []
        for file in files[offset : offset + limit]:
            try:
                data = json.loads(file.read_text(encoding="utf-8-sig"))
                results.append({
                    "workflow_id": data.get("workflow_id", file.stem),
                    "user_query": data.get("user_query"),
                    "business_category": data.get("business_category"),
                    "search_location": data.get("search_location"),
                    "candidates_count": data.get("candidates_count", 0),
                    "selected_lead_id": data.get("selected_lead_id"),
                    "execution_status": data.get("execution_status"),
                    "approval_status": data.get("approval_status"),
                    "updated_at": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(),
                })
            except Exception:
                continue
        return results

    async def start_discovery(
        self,
        query: str,
        location: str | None = None,
        limit: int = 10,
        priority: str | None = None,
    ) -> WorkflowState:
        """Stage A: Start new workflow and discover leads."""
        workflow_id = uuid.uuid4().hex
        thread_id = workflow_id

        initial_state: WorkflowState = {
            "workflow_id": workflow_id,
            "thread_id": thread_id,
            "user_query": query,
            "search_location": location or "",
            "business_category": "",
            "discovery_limit": limit,
            "priority_filter": priority,
            "discovered_leads": [],
            "candidates_count": 0,
            "selected_lead_id": None,
            "selected_lead": None,
            "research_results": None,
            "source_documents": [],
            "retrieved_context": [],
            "lead_score": None,
            "proposal": None,
            "outreach_email": None,
            "approval_status": "pending",
            "outreach_channel": "none",
            "outreach_result": None,
            "execution_status": "START",
            "errors": [],
            "execution_metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "workflow_id": workflow_id,
            },
        }

        config = {"configurable": {"thread_id": thread_id}}
        final_state = await self.graph.ainvoke(initial_state, config=config)
        self._save_workflow(workflow_id, final_state)
        return final_state

    async def select_lead_and_resume(
        self,
        workflow_id: str,
        lead_id: str,
    ) -> WorkflowState:
        """Stage B–E: Resume workflow with selected lead through research, RAG, and proposal generation."""
        state = self.get_workflow(workflow_id)
        if not state:
            raise LookupError(f"Workflow '{workflow_id}' not found.")

        # Validate that selected lead exists in discovered leads or store
        state["selected_lead_id"] = lead_id
        state["execution_status"] = "LEAD_SELECTION_RECEIVED"

        config = {"configurable": {"thread_id": state.get("thread_id", workflow_id)}}
        final_state = await self.graph.ainvoke(state, config=config)
        self._save_workflow(workflow_id, final_state)
        return final_state

    async def approve_and_send_outreach(
        self,
        workflow_id: str,
        channel: str = "email",
        approved_proposal: dict[str, Any] | None = None,
        approved_email: dict[str, Any] | None = None,
    ) -> WorkflowState:
        """Stage F: Explicitly approve proposal and trigger outreach (email / voice)."""
        state = self.get_workflow(workflow_id)
        if not state:
            raise LookupError(f"Workflow '{workflow_id}' not found.")

        state["approval_status"] = "approved"
        state["outreach_channel"] = channel
        if approved_proposal:
            state["approved_proposal"] = approved_proposal
        if approved_email:
            state["approved_outreach_email"] = approved_email

        config = {"configurable": {"thread_id": state.get("thread_id", workflow_id)}}
        final_state = await self.graph.ainvoke(state, config=config)
        self._save_workflow(workflow_id, final_state)
        return final_state


# Global orchestrator singleton instance
_orchestrator: LeadSutraOrchestrator | None = None


def get_orchestrator() -> LeadSutraOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = LeadSutraOrchestrator()
    return _orchestrator
