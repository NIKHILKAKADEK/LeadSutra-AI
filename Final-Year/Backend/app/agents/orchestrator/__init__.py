"""LangGraph workflow orchestration agent."""
from importlib import import_module

from .schema import WorkflowState

__all__ = ["LeadSutraOrchestrator", "WorkflowState", "build_leadsutra_graph", "get_orchestrator"]


def __getattr__(name: str):
    if name in {"LeadSutraOrchestrator", "build_leadsutra_graph", "get_orchestrator"}:
        agent = import_module(".agent", __name__)
        return getattr(agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
