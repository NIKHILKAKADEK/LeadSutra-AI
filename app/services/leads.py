from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models.leads import LeadFileError, PreparedLead, SourceLead, prepare_lead
from app.agents.lead_pipeline.schemas import LeadResult


class LeadJsonService:
    """Read and validate the configured lead JSON without modifying it."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def load(self) -> list[PreparedLead]:
        if self._path.is_dir():
            # Read published Step 5 runs; staging directories are never lead sources.
            try:
                paths = sorted(
                    (path for path in self._path.glob('*/leads.json')
                     if not path.parent.name.startswith('.')),
                    key=lambda path: (path.stat().st_mtime_ns, str(path)), reverse=True,
                )
            except OSError:
                raise LeadFileError('Lead JSON files could not be read.') from None
            by_id: dict[str, PreparedLead] = {}
            for path in paths:
                for lead in LeadJsonService(path).load():
                    by_id.setdefault(lead.lead_id, lead)
            return list(by_id.values())
        try:
            with self._path.open('r', encoding='utf-8-sig') as stream:
                payload: Any = json.load(stream)
        except FileNotFoundError:
            raise LeadFileError('Lead JSON file is not available.') from None
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise LeadFileError('Lead JSON file could not be read.') from None
        if not isinstance(payload, list):
            raise LeadFileError('Lead JSON must contain an array of lead records.')
        prepared: list[PreparedLead] = []
        for index, item in enumerate(payload):
            try:
                if isinstance(item, dict) and any(key in item for key in ('discovery', 'enrichment', 'scoring')):
                    lead = LeadResult.model_validate(item)
                    item = {
                        'lead_id': lead.lead_id,
                        'business': lead.discovery.model_dump(mode='json'),
                        'contacts': lead.enrichment.model_dump(mode='json'),
                        'lead_scoring': lead.scoring.model_dump(mode='json'),
                    }
                source = SourceLead.model_validate(item)
            except ValidationError:
                raise LeadFileError(f'Lead record {index} does not match the expected structure.') from None
            prepared.append(prepare_lead(source))
        return prepared
