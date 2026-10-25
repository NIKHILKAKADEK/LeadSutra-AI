from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.mongodb import get_mongo_collection


class ResearchOutputService:
    """Store grounded research output in MongoDB."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.collection = get_mongo_collection("research")

    def _collection(self):
        if self.collection is None:
            raise RuntimeError("MongoDB must be configured to store research results.")
        return self.collection

    @staticmethod
    def _validate_lead_id(lead_id: str) -> None:
        if not lead_id or any(c in lead_id for c in "/\\..\0"):
            raise ValueError("Research output ID is invalid.")

    def save(self, lead_id: str, research: dict[str, Any]) -> str:
        self._validate_lead_id(lead_id)
        payload = json.loads(json.dumps(research, ensure_ascii=False, allow_nan=False))
        if not isinstance(payload, dict):
            raise ValueError("Research output must be an object.")
        now = datetime.now(timezone.utc)
        self._collection().update_one(
            {"_id": lead_id},
            {
                "$set": {"lead_id": lead_id, "result": payload, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return lead_id

    def load(self, lead_id: str) -> dict[str, Any] | None:
        self._validate_lead_id(lead_id)
        collection = self._collection()
        document = collection.find_one({"_id": lead_id}, {"result": 1})
        if document is not None:
            result = document.get("result")
            return result if isinstance(result, dict) else None

        legacy_path = (self.root / lead_id / "research.txt").resolve()
        if not legacy_path.is_relative_to(self.root) or legacy_path.parent == self.root:
            raise ValueError("Research output ID is invalid.")
        try:
            result = json.loads(legacy_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("Legacy research result could not be read.") from None
        if not isinstance(result, dict):
            raise ValueError("Legacy research result is invalid.")
        self.save(lead_id, result)
        return result

    def save_competitors(self, lead_id: str, analysis: dict[str, Any]) -> None:
        self._validate_lead_id(lead_id)
        payload = json.loads(json.dumps(analysis, ensure_ascii=False, allow_nan=False))
        if not isinstance(payload, dict):
            raise ValueError("Competitor analysis must be an object.")
        now = datetime.now(timezone.utc)
        self._collection().update_one(
            {"_id": lead_id},
            {
                "$set": {
                    "lead_id": lead_id,
                    "competitor_analysis": payload,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def load_competitors(self, lead_id: str) -> dict[str, Any] | None:
        self._validate_lead_id(lead_id)
        document = self._collection().find_one(
            {"_id": lead_id},
            {"competitor_analysis": 1},
        )
        analysis = document.get("competitor_analysis") if document else None
        return analysis if isinstance(analysis, dict) else None
