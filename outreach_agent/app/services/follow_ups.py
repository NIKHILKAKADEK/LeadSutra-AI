"""SQLite persistence for reviewer-managed follow-ups."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.models.call_history import FollowUpCreate, FollowUpStatus, FollowUpUpdate


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required.")
    return value.astimezone(timezone.utc).isoformat()


class FollowUpStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS follow_ups (
                follow_up_id TEXT PRIMARY KEY,
                lead_id TEXT NOT NULL,
                related_call_id TEXT,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL,
                assigned_reviewer TEXT,
                notes TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def create(self, payload: FollowUpCreate) -> tuple[dict[str, Any], bool]:
        scheduled = _utc(payload.scheduled_at)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM follow_ups WHERE idempotency_key=?",
                                  (str(payload.idempotency_key),)).fetchone()
            if existing:
                if (existing["lead_id"] != payload.lead_id or
                    existing["related_call_id"] != (str(payload.related_call_id) if payload.related_call_id else None) or
                    existing["scheduled_at"] != scheduled or existing["notes"] != payload.notes):
                    raise ValueError("Idempotency key was already used for another follow-up.")
                return self._record(existing), False
            follow_up_id = str(uuid4())
            db.execute("INSERT INTO follow_ups VALUES (?,?,?,?,?,?,?,?,?,?)", (
                follow_up_id, payload.lead_id,
                str(payload.related_call_id) if payload.related_call_id else None,
                scheduled, FollowUpStatus.pending.value, None, payload.notes,
                str(payload.idempotency_key), now, now,
            ))
            row = db.execute("SELECT * FROM follow_ups WHERE follow_up_id=?", (follow_up_id,)).fetchone()
        return self._record(row), True

    def get(self, follow_up_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM follow_ups WHERE follow_up_id=?", (follow_up_id,)).fetchone()
        return self._record(row) if row else None

    def list(self, *, lead_id: str | None, status: FollowUpStatus | None,
             limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []
        if lead_id is not None:
            clauses.append("lead_id=?")
            values.append(lead_id)
        if status is not None:
            clauses.append("status=?")
            values.append(status.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) FROM follow_ups" + where, values).fetchone()[0]
            rows = db.execute("SELECT * FROM follow_ups" + where +
                              " ORDER BY scheduled_at, follow_up_id LIMIT ? OFFSET ?",
                              [*values, limit, offset]).fetchall()
        return [self._record(row) for row in rows], total

    def update(self, follow_up_id: str, payload: FollowUpUpdate) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM follow_ups WHERE follow_up_id=?", (follow_up_id,)).fetchone()
            if not row:
                return None
            current = FollowUpStatus(row["status"])
            if payload.status is not None:
                if current != FollowUpStatus.pending or payload.status == FollowUpStatus.pending:
                    raise ValueError("Completed or cancelled follow-ups cannot be reopened or re-transitioned.")
            if current != FollowUpStatus.pending and payload.scheduled_at is not None:
                raise ValueError("Terminal follow-ups cannot be rescheduled.")
            scheduled = _utc(payload.scheduled_at) if payload.scheduled_at is not None else row["scheduled_at"]
            new_status = payload.status.value if payload.status is not None else current.value
            notes = payload.notes if "notes" in payload.model_fields_set else row["notes"]
            db.execute("UPDATE follow_ups SET scheduled_at=?, status=?, notes=?, updated_at=? WHERE follow_up_id=?",
                       (scheduled, new_status, notes, datetime.now(timezone.utc).isoformat(), follow_up_id))
            updated = db.execute("SELECT * FROM follow_ups WHERE follow_up_id=?", (follow_up_id,)).fetchone()
        return self._record(updated)
