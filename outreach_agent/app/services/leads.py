from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models.leads import LeadFileError, PreparedLead, SourceLead, prepare_lead


class LeadJsonService:
    """Read and validate the configured lead JSON without modifying it."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def load(self) -> list[PreparedLead]:
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
                source = SourceLead.model_validate(item)
            except ValidationError:
                raise LeadFileError(f'Lead record {index} does not match the expected structure.') from None
            prepared.append(prepare_lead(source))
        return prepared
