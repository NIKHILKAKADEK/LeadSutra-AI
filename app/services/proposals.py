"""Read and write server-controlled proposal artifacts with lead association."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.proposal import ProposalResult


class ProposalFileError(Exception):
    """An existing proposal could not be safely associated with its lead."""


class ProposalJsonService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _lead_path(self, lead_id: str, filename: str = "proposal.json") -> Path:
        if not lead_id or not isinstance(lead_id, str) or any(c in lead_id for c in "/\\..\0"):
            raise ProposalFileError("Proposal path is invalid.")
        path = (self.root / lead_id / filename).resolve()
        if not path.is_relative_to(self.root) or path.parent == self.root:
            raise ProposalFileError("Proposal path is invalid.")
        return path

    def load(self, lead_id: str) -> ProposalResult | None:
        path = self._lead_path(lead_id, "proposal.json")
        try:
            proposal = ProposalResult.model_validate_json(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, ValidationError):
            raise ProposalFileError("Proposal artifact could not be read or validated.") from None
        if proposal.lead_id != lead_id:
            raise ProposalFileError("Proposal artifact belongs to another lead.")
        return proposal

    def load_rich(self, lead_id: str) -> dict[str, Any] | None:
        """Load the full generated proposal JSON if present."""
        path = self._lead_path(lead_id, "rich_proposal.json")
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None

    def save(
        self,
        lead_id: str,
        proposal: ProposalResult | dict[str, Any],
        rich_proposal: dict[str, Any] | None = None,
    ) -> Path:
        """Persist canonical proposal and optional rich proposal artifact."""
        path = self._lead_path(lead_id, "proposal.json")
        path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(proposal, ProposalResult):
            canonical = proposal
        elif isinstance(proposal, dict):
            # If the caller provided a rich proposal dict, convert to canonical ProposalResult fields
            if "lead_id" in proposal and all(k in {"lead_id", "business_context", "proposed_service", "approved_product_facts", "approved_pricing"} for k in proposal.keys()):
                canonical = ProposalResult.model_validate(proposal)
            else:
                rich_proposal = rich_proposal or dict(proposal)
                pricing = proposal.get("pricing_suggestion")
                if isinstance(pricing, str) and pricing.casefold() in {"not available from provided data", "not available", "none"}:
                    pricing = None
                deliverables = proposal.get("deliverables")
                facts = ", ".join(deliverables) if isinstance(deliverables, list) and deliverables else None
                canonical = ProposalResult(
                    lead_id=lead_id,
                    business_context=proposal.get("business_summary") or None,
                    proposed_service=proposal.get("proposed_solution") or None,
                    approved_product_facts=facts,
                    approved_pricing=pricing,
                )
        else:
            raise ProposalFileError("Unsupported proposal object type.")

        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(canonical.model_dump_json(indent=2), encoding="utf-8")
        temp_path.replace(path)

        if rich_proposal:
            rich_path = self._lead_path(lead_id, "rich_proposal.json")
            rich_temp = rich_path.with_suffix(".tmp")
            rich_temp.write_text(json.dumps(rich_proposal, indent=2, ensure_ascii=False), encoding="utf-8")
            rich_temp.replace(rich_path)

        return path
