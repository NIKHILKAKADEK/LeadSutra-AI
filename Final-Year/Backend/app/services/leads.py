from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.agents.lead_pipeline.schema import LeadResult
from app.models.leads import LeadFileError, PreparedLead, SourceLead, prepare_lead
from app.services.lead_results import LeadResultStore


class LeadJsonService:
    """Adapt canonical MongoDB leads to the existing outreach service contract."""

    def __init__(self, path: str | Path | None = None):
        self._legacy_path = Path(path) if path is not None else None

    @staticmethod
    def _source_lead(lead: LeadResult) -> PreparedLead:
        item = {
            "lead_id": lead.lead_id,
            "business": lead.discovery.model_dump(mode="json"),
            "contacts": lead.enrichment.model_dump(mode="json"),
            "lead_scoring": lead.scoring.model_dump(mode="json"),
        }
        try:
            return prepare_lead(SourceLead.model_validate(item))
        except ValidationError:
            raise LeadFileError("Stored lead record does not match the expected structure.") from None

    def load(self) -> list[PreparedLead]:
        try:
            records = LeadResultStore(self._legacy_path).list_all_records()
        except (OSError, ValueError, RuntimeError):
            raise LeadFileError("Lead source is unavailable.") from None
        return [self._source_lead(lead) for lead in records]
