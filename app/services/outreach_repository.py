"""Existing SQLite dispatch ledger; schema and semantics preserved."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.schemas.outreach import DispatchStatus


class DispatchLedger:
    """Durable idempotency ledger; a claimed key is never silently retried."""

    def __init__(self, path: str | Path):
        self.path = str(path)

        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS call_dispatch_ledger (
                    idempotency_key TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_request_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def lookup(
        self,
        key: UUID | str,
    ) -> tuple[str, str, str | None] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT lead_id, phone_number, status
                FROM call_dispatch_ledger
                WHERE idempotency_key=?
                """,
                (str(key),),
            ).fetchone()

        return (row[0], row[1], row[2]) if row else None

    def claim(
        self,
        key: UUID | str,
        lead_id: str,
        phone: str,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()

        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO call_dispatch_ledger VALUES (?,?,?,?,?,?,?)",
                    (str(key), lead_id, phone, "dispatching", None, now, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def finish(
        self,
        key: UUID | str,
        status: DispatchStatus,
        provider_request_id: str | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE call_dispatch_ledger
                SET status=?, provider_request_id=?, updated_at=?
                WHERE idempotency_key=?
                """,
                (
                    status.value,
                    provider_request_id,
                    datetime.now(timezone.utc).isoformat(),
                    str(key),
                ),
            )

    def list_records(
        self,
        *,
        lead_id: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []

        if lead_id is not None:
            clauses.append("lead_id=?")
            values.append(lead_id)

        if status is not None:
            clauses.append("status=?")
            values.append(status)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM call_dispatch_ledger" + where,
                values,
            ).fetchone()[0]

            rows = db.execute(
                "SELECT idempotency_key, lead_id, phone_number, status, "
                "provider_request_id, created_at, updated_at "
                "FROM call_dispatch_ledger"
                + where
                + " ORDER BY created_at DESC, idempotency_key LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()

        return (
            [
                {
                    "call_id": row[0],
                    "lead_id": row[1],
                    "phone_number": row[2],
                    "dispatch_status": row[3],
                    "provider_request_id": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                    "dispatch_requested": row[3] in {
                        DispatchStatus.dispatched.value,
                        DispatchStatus.provider_error.value,
                        DispatchStatus.uncertain.value,
                    },
                    "provider_accepted": (
                        row[3] == DispatchStatus.dispatched.value
                    ),
                    "call_outcome": "unknown",
                }
                for row in rows
            ],
            total,
        )

    def get_record(self, call_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT idempotency_key, lead_id, phone_number, status,
                       provider_request_id, created_at, updated_at
                FROM call_dispatch_ledger
                WHERE idempotency_key=?
                """,
                (call_id,),
            ).fetchone()

        if not row:
            return None

        return {
            "call_id": row[0],
            "lead_id": row[1],
            "phone_number": row[2],
            "dispatch_status": row[3],
            "provider_request_id": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "dispatch_requested": row[3] in {
                DispatchStatus.dispatched.value,
                DispatchStatus.provider_error.value,
                DispatchStatus.uncertain.value,
            },
            "provider_accepted": row[3] == DispatchStatus.dispatched.value,
            "call_outcome": "unknown",
        }