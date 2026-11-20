"""LeadSutra AI LangGraph orchestration engine."""

from importlib import import_module

__all__ = [
    "LeadSutraOrchestrator",
    "WorkflowState",
    "build_leadsutra_graph",
    "get_orchestrator",
]


def __getattr__(name: str):
    if name == "WorkflowState":
        from app.agents.orchestrator.schema import WorkflowState

        return WorkflowState
    if name in {"LeadSutraOrchestrator", "build_leadsutra_graph", "get_orchestrator"}:
        agent = import_module("app.agents.orchestrator.agent")
        return getattr(agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
