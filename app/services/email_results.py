"""One SQLite email/approval store, with atomic claims and explicit connection closure."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from app.schemas.email import EmailDraft, EmailResult


_INSERT = """INSERT INTO email_results
    (email_id, lead_id, review_id, business_name, recipient, sender, proposal_file,
     status, created_at, sent_at, message_id, error)
    VALUES (:email_id,:lead_id,:review_id,:business_name,:recipient,:sender,:proposal_file,
            :status,:created_at,:sent_at,:message_id,:error)"""

class EmailResultStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS email_approvals (
                review_id TEXT PRIMARY KEY, approved INTEGER NOT NULL,
                approved_by TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS email_results (
                email_id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, review_id TEXT UNIQUE,
                business_name TEXT, recipient TEXT, sender TEXT, proposal_file TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL, sent_at TEXT,
                message_id TEXT, error TEXT)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def approved(self, review_id: str) -> bool:
        with closing(self._connect()) as db:
            row = db.execute("SELECT approved FROM email_approvals WHERE review_id=?", (review_id,)).fetchone()
        return bool(row and row[0])

    def set_approval(self, review_id: str, approved: bool, principal: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("""INSERT INTO email_approvals VALUES (?,?,?,?)
                ON CONFLICT(review_id) DO UPDATE SET approved=excluded.approved,
                approved_by=excluded.approved_by, updated_at=excluded.updated_at""",
                (review_id, int(approved), principal, datetime.now(timezone.utc).isoformat()))

    def enqueue(self, draft: EmailDraft) -> tuple[EmailResult, bool]:
        result = EmailResult(email_id=uuid4(), lead_id=draft.lead_id, review_id=draft.review_id,
                             business_name=draft.business_name, recipient=draft.recipient,
                             sender=draft.sender, proposal_file=draft.proposal_file,
                             status="pending", created_at=datetime.now(timezone.utc))
        with closing(self._connect()) as db, db:
            inserted = db.execute(_INSERT + " ON CONFLICT(review_id) DO NOTHING", result.model_dump(mode="json"))
            is_new = inserted.rowcount == 1
            if not is_new:
                updated = db.execute(
                    "UPDATE email_results SET status='pending', error=NULL, sent_at=NULL, message_id=NULL "
                    "WHERE review_id=? AND status IN ('failed', 'uncertain')",
                    (draft.review_id,)
                )
                is_retry = updated.rowcount == 1
            else:
                is_retry = False
            row = db.execute("SELECT * FROM email_results WHERE review_id=?", (draft.review_id,)).fetchone()
        return EmailResult.model_validate(dict(row)), (is_new or is_retry)

    def record_failure(self, lead_id: str, error: str) -> EmailResult:
        result = EmailResult(email_id=uuid4(), lead_id=lead_id, status="failed",
                             created_at=datetime.now(timezone.utc), error=error)
        with closing(self._connect()) as db, db:
            db.execute(_INSERT, result.model_dump(mode="json"))
        return result

    def get(self, email_id: UUID | str) -> EmailResult | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM email_results WHERE email_id=?", (str(email_id),)).fetchone()
        return EmailResult.model_validate(dict(row)) if row else None

    def list_records(
        self, *, status: str | None = None, limit: int = 25, offset: int = 0,
    ) -> tuple[list[EmailResult], int]:
        """Read a consistent count/page snapshot from the existing results table."""
        where = " WHERE status=?" if status is not None else ""
        values = [status] if status is not None else []
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*) FROM email_results" + where, values).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM email_results" + where
                + " ORDER BY created_at DESC, email_id LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        return [EmailResult.model_validate(dict(row)) for row in rows], total

    def claim(self, email_id: UUID | str) -> EmailResult | None:
        with closing(self._connect()) as db, db:
            cursor = db.execute("UPDATE email_results SET status='sending' WHERE email_id=? AND status='pending'",
                                (str(email_id),))
            row = db.execute("SELECT * FROM email_results WHERE email_id=?", (str(email_id),)).fetchone()
        return EmailResult.model_validate(dict(row)) if cursor.rowcount else None

    def finish(self, email_id: UUID | str, status: str, error: str | None = None,
               message_id: str | None = None) -> None:
        sent_at = datetime.now(timezone.utc).isoformat() if status == "sent" else None
        with closing(self._connect()) as db, db:
            db.execute("UPDATE email_results SET status=?, sent_at=?, message_id=?, error=? WHERE email_id=? AND status='sending'",
                       (status, sent_at, message_id, error, str(email_id)))
