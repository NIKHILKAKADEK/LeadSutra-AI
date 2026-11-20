from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.database.mongodb import get_mongo_collection
from app.schemas.outreach import DispatchStatus


class DispatchLedger:
    """MongoDB idempotency ledger; a claimed key is never silently retried."""

    def __init__(self, path: str | Path | None = None):
        self.legacy_path = Path(path) if path is not None and str(path) != ":memory:" else None
        self.collection = get_mongo_collection("call_dispatches")
        self.migrations = get_mongo_collection("migrations")

    def _require_collection(self) -> Any:
        if self.collection is None:
            raise RuntimeError("MongoDB must be configured to store call records.")
        return self.collection

    def _migrate_legacy_sqlite(self) -> None:
        if (
            self.legacy_path is None
            or not self.legacy_path.is_file()
            or self.migrations is None
            or self.collection is None
        ):
            return
        marker = "call-dispatch-sqlite-v1"
        if self.migrations.find_one({"_id": marker}, {"_id": 1}):
            return

        uri = self.legacy_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            table_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='call_dispatch_ledger'"
            ).fetchone()
            if table_exists:
                for row in db.execute("SELECT * FROM call_dispatch_ledger"):
                    item = dict(row)
                    item["_id"] = item["idempotency_key"]
                    for field in ("created_at", "updated_at"):
                        item[field] = datetime.fromisoformat(item[field])
                    self.collection.update_one(
                        {"_id": item["_id"]},
                        {"$setOnInsert": item},
                        upsert=True,
                    )
        self.migrations.update_one(
            {"_id": marker},
            {"$setOnInsert": {"completed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def lookup(self, key: UUID | str) -> tuple[str, str, str | None] | None:
        collection = self._require_collection()
        self._migrate_legacy_sqlite()
        row = collection.find_one(
            {"_id": str(key)},
            {"lead_id": 1, "phone_number": 1, "status": 1},
        )
        return (row["lead_id"], row["phone_number"], row["status"]) if row else None

    def claim(self, key: UUID | str, lead_id: str, phone: str) -> bool:
        collection = self._require_collection()
        self._migrate_legacy_sqlite()
        now = datetime.now(timezone.utc)
        try:
            collection.insert_one({
                "_id": str(key),
                "idempotency_key": str(key),
                "lead_id": lead_id,
                "phone_number": phone,
                "status": DispatchStatus.dispatching.value,
                "provider_request_id": None,
                "created_at": now,
                "updated_at": now,
            })
        except Exception as exc:
            if getattr(exc, "code", None) == 11000:
                return False
            raise
        return True

    def finish(
        self,
        key: UUID | str,
        status: DispatchStatus,
        provider_request_id: str | None = None,
    ) -> None:
        self._require_collection().update_one(
            {"_id": str(key)},
            {"$set": {
                "status": status.value,
                "provider_request_id": provider_request_id,
                "updated_at": datetime.now(timezone.utc),
            }},
        )

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        status = record["status"]
        return {
            "call_id": record["idempotency_key"],
            "lead_id": record["lead_id"],
            "phone_number": record["phone_number"],
            "dispatch_status": status,
            "provider_request_id": record.get("provider_request_id"),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "dispatch_requested": status in {
                DispatchStatus.dispatched.value,
                DispatchStatus.provider_error.value,
                DispatchStatus.uncertain.value,
            },
            "provider_accepted": status == DispatchStatus.dispatched.value,
            "call_outcome": "unknown",
        }

    def list_records(
        self,
        *,
        lead_id: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        collection = self._require_collection()
        self._migrate_legacy_sqlite()
        query: dict[str, Any] = {}
        if lead_id is not None:
            query["lead_id"] = lead_id
        if status is not None:
            query["status"] = status
        total = collection.count_documents(query)
        records = (
            collection.find(query)
            .sort([("created_at", -1), ("_id", 1)])
            .skip(offset)
            .limit(limit)
        )
        return [self._public_record(record) for record in records], total

    def get_record(self, call_id: str) -> dict[str, Any] | None:
        collection = self._require_collection()
        self._migrate_legacy_sqlite()
        record = collection.find_one({"_id": call_id})
        return self._public_record(record) if record else None
