"""Read a server-controlled proposal artifact without generating or altering it."""

from pathlib import Path

from pydantic import ValidationError

from app.schemas.proposal import ProposalResult


class ProposalFileError(Exception):
    """An existing proposal could not be safely associated with its lead."""


class ProposalJsonService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def load(self, lead_id: str) -> ProposalResult | None:
        path = (self.root / lead_id / "proposal.json").resolve()
        if not path.is_relative_to(self.root) or path.parent == self.root:
            raise ProposalFileError("Proposal path is invalid.")
        try:
            proposal = ProposalResult.model_validate_json(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            # Absence preserves the original dispatch/context behavior.
            return None
        except (OSError, UnicodeError, ValidationError):
            raise ProposalFileError("Proposal artifact could not be read or validated.") from None
        if proposal.lead_id != lead_id:
            raise ProposalFileError("Proposal artifact belongs to another lead.")
        return proposal
