"""Proposal generation agent and its contracts."""
from .agent import proposal_agent
from .schema import ProposalGenerationRequest, ProposalGenerationResponse, ProposalResult

__all__ = [
    "ProposalGenerationRequest",
    "ProposalGenerationResponse",
    "ProposalResult",
    "proposal_agent",
]
