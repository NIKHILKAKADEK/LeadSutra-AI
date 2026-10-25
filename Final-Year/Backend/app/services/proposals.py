from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agents.voice.schema import ProposalResult
from app.database.mongodb import get_mongo_collection


class ProposalFileError(Exception):
    """A proposal could not be safely loaded or associated with its lead."""


class ProposalJsonService:
    """Store canonical and rich proposal results in MongoDB."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.collection = get_mongo_collection("proposals")

    def _collection(self):
        if self.collection is None:
            raise RuntimeError("MongoDB must be configured to store proposal results.")
        return self.collection

    def _lead_path(self, lead_id: str, filename: str = "proposal.json") -> Path:
        if not lead_id or any(c in lead_id for c in "/\\..\0"):
            raise ProposalFileError("Proposal path is invalid.")
        path = (self.root / lead_id / filename).resolve()
        if not path.is_relative_to(self.root) or path.parent == self.root:
            raise ProposalFileError("Proposal path is invalid.")
        return path

    def load(self, lead_id: str) -> ProposalResult | None:
        document = self._collection().find_one({"_id": lead_id})
        if document is not None:
            if document.get("lead_id") != lead_id:
                raise ProposalFileError("Proposal belongs to another lead.")
            try:
                return ProposalResult.model_validate(document["proposal"])
            except (KeyError, ValidationError):
                raise ProposalFileError("Proposal record could not be validated.") from None

        path = self._lead_path(lead_id)
        try:
            canonical = ProposalResult.model_validate_json(path.read_text(encoding="utf-8-sig"))
            rich_path = self._lead_path(lead_id, "rich_proposal.json")
            rich = json.loads(rich_path.read_text(encoding="utf-8-sig")) if rich_path.is_file() else None
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
            raise ProposalFileError("Legacy proposal artifact could not be read or validated.") from None
        if canonical.lead_id != lead_id:
            raise ProposalFileError("Proposal artifact belongs to another lead.")
        self.save(lead_id, canonical, rich)
        return canonical

    def load_rich(self, lead_id: str) -> dict[str, Any] | None:
        document = self._collection().find_one({"_id": lead_id}, {"rich_proposal": 1})
        if document is not None:
            rich = document.get("rich_proposal")
            return rich if isinstance(rich, dict) else None
        self.load(lead_id)
        document = self._collection().find_one({"_id": lead_id}, {"rich_proposal": 1})
        if document is None:
            return None
        rich = document.get("rich_proposal")
        return rich if isinstance(rich, dict) else None

    def save(
        self,
        lead_id: str,
        proposal: ProposalResult | dict[str, Any],
        rich_proposal: dict[str, Any] | None = None,
    ) -> str:
        if not lead_id:
            raise ProposalFileError("Proposal lead ID is invalid.")
        if isinstance(proposal, ProposalResult):
            canonical = proposal
        elif isinstance(proposal, dict):
            if "lead_id" in proposal and all(
                key in {"lead_id", "business_context", "proposed_service", "approved_product_facts", "approved_pricing"}
                for key in proposal
            ):
                canonical = ProposalResult.model_validate(proposal)
            else:
                rich_proposal = rich_proposal or dict(proposal)
                pricing = proposal.get("pricing_suggestion")
                if isinstance(pricing, str) and pricing.casefold() in {
                    "not available from provided data", "not available", "none",
                }:
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
        if canonical.lead_id != lead_id:
            raise ProposalFileError("Proposal belongs to another lead.")

        update: dict[str, Any] = {
            "lead_id": lead_id,
            "proposal": canonical.model_dump(mode="json"),
            "updated_at": datetime.now(timezone.utc),
        }
        if rich_proposal is not None:
            update["rich_proposal"] = json.loads(
                json.dumps(rich_proposal, ensure_ascii=False, allow_nan=False)
            )
        self._collection().update_one(
            {"_id": lead_id},
            {"$set": update, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return lead_id
