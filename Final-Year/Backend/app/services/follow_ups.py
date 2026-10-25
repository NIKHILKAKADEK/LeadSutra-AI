from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.database.mongodb import get_mongo_collection
from app.schemas.follow_ups import FollowUpCreate, FollowUpUpdate


class FollowUpStore:
    def __init__(self) -> None:
        self.collection = get_mongo_collection("follow_ups")

    def _collection(self) -> Any:
        if self.collection is None:
            raise RuntimeError("MongoDB must be configured to store follow-ups.")
        return self.collection

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "follow_up_id": row["_id"],
            "lead_id": row["lead_id"],
            "related_call_id": row.get("related_call_id"),
            "scheduled_at": row["scheduled_at"],
            "status": row["status"],
            "assigned_reviewer": row.get("assigned_reviewer"),
            "notes": row.get("notes"),
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create(self, payload: FollowUpCreate, reviewer: str) -> dict[str, Any]:
        collection = self._collection()
        key = str(payload.idempotency_key)
        current = collection.find_one({"idempotency_key": key})
        if current:
            if current["lead_id"] != payload.lead_id:
                raise ValueError("Idempotency key was already used for another follow-up.")
            return self._public(current)
        now = datetime.now(timezone.utc)
        row = {
            "_id": key,
            "lead_id": payload.lead_id,
            "related_call_id": None,
            "scheduled_at": payload.scheduled_at,
            "status": "pending",
            "assigned_reviewer": reviewer,
            "notes": payload.notes,
            "idempotency_key": key,
            "created_at": now,
            "updated_at": now,
        }
        try:
            collection.insert_one(row)
        except Exception as exc:
            if getattr(exc, "code", None) != 11000:
                raise
            existing = collection.find_one({"idempotency_key": key})
            if not existing:
                raise
            return self._public(existing)
        return self._public(row)

    def list(self, *, status: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        collection = self._collection()
        query = {"status": status} if status else {}
        total = collection.count_documents(query)
        rows = collection.find(query).sort([("scheduled_at", 1), ("_id", 1)]).skip(offset).limit(limit)
        return [self._public(row) for row in rows], total

    def get(self, follow_up_id: UUID) -> dict[str, Any] | None:
        row = self._collection().find_one({"_id": str(follow_up_id)})
        return self._public(row) if row else None

    def update(self, follow_up_id: UUID, changes: FollowUpUpdate) -> dict[str, Any] | None:
        values = changes.model_dump(exclude_unset=True)
        if not values:
            return self.get(follow_up_id)
        values["updated_at"] = datetime.now(timezone.utc)
        self._collection().update_one({"_id": str(follow_up_id)}, {"$set": values})
        return self.get(follow_up_id)
