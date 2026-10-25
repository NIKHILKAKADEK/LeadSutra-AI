from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from typing import Any

from app.agents.email.schema import EmailDraft, EmailResult
from app.database.mongodb import get_mongo_collection


class EmailResultStore:
    """Persist email approvals and delivery records in MongoDB."""

    def __init__(self, path: str | Path | None = None):
        self.legacy_path = Path(path) if path is not None and str(path) != ":memory:" else None
        self.results = get_mongo_collection("email_results")
        self.approvals = get_mongo_collection("email_approvals")
        self.drafts = get_mongo_collection("email_drafts")
        self.migrations = get_mongo_collection("migrations")

    def _require_results(self) -> Any:
        if self.results is None or self.approvals is None:
            raise RuntimeError("MongoDB must be configured to store email results.")
        return self.results

    def generated_draft(self, fingerprint: str) -> tuple[str, str] | None:
        if self.drafts is None:
            raise RuntimeError("MongoDB must be configured to store generated email drafts.")
        record = self.drafts.find_one({"_id": fingerprint}, {"subject": 1, "body": 1})
        if not record or not isinstance(record.get("subject"), str) or not isinstance(record.get("body"), str):
            return None
        return record["subject"], record["body"]

    def generated_template(self, fingerprint: str) -> str | None:
        if self.drafts is None:
            raise RuntimeError("MongoDB must be configured to store generated email drafts.")
        record = self.drafts.find_one({"_id": fingerprint}, {"template": 1})
        template = record.get("template") if record else None
        return template if isinstance(template, str) else None

    def save_generated_draft(
        self, fingerprint: str, subject: str, body: str, *,
        lead_id: str, template: str, replace: bool = False,
    ) -> tuple[str, str]:
        if self.drafts is None:
            raise RuntimeError("MongoDB must be configured to store generated email drafts.")
        values = {
                "subject": subject, "body": body,
                "lead_id": lead_id, "template": template,
                "created_at": datetime.now(timezone.utc),
            }
        self.drafts.update_one(
            {"_id": fingerprint},
            {"$set": values} if replace else {"$setOnInsert": values},
            upsert=True,
        )
        # If concurrent previews generated different text, use the first saved version.
        return self.generated_draft(fingerprint) or (subject, body)

    def _migrate_legacy_sqlite(self) -> None:
        if (
            self.legacy_path is None
            or not self.legacy_path.is_file()
            or self.migrations is None
            or self.results is None
            or self.approvals is None
        ):
            return
        marker = "email-sqlite-v1"
        if self.migrations.find_one({"_id": marker}, {"_id": 1}):
            return

        uri = self.legacy_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "email_approvals" in tables:
                for row in db.execute("SELECT * FROM email_approvals"):
                    item = dict(row)
                    self.approvals.update_one(
                        {"_id": item["review_id"]},
                        {"$setOnInsert": {
                            "approved": bool(item["approved"]),
                            "approved_by": item["approved_by"],
                            "updated_at": datetime.fromisoformat(item["updated_at"]),
                        }},
                        upsert=True,
                    )
            if "email_results" in tables:
                for row in db.execute("SELECT * FROM email_results"):
                    item = dict(row)
                    item["email_id"] = str(item["email_id"])
                    item["_id"] = item["email_id"]
                    for field in ("created_at", "sent_at"):
                        if item.get(field):
                            item[field] = datetime.fromisoformat(item[field])
                    self.results.update_one(
                        {"_id": item["_id"]},
                        {"$setOnInsert": item},
                        upsert=True,
                    )
        self.migrations.update_one(
            {"_id": marker},
            {"$setOnInsert": {"completed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    @staticmethod
    def _result(document: dict[str, Any] | None) -> EmailResult | None:
        if document is None:
            return None
        result = {key: value for key, value in document.items() if key != "_id"}
        return EmailResult.model_validate(result)

    def approved(self, review_id: str) -> bool:
        self._require_results()
        self._migrate_legacy_sqlite()
        record = self.approvals.find_one({"_id": review_id}, {"approved": 1})
        return bool(record and record.get("approved"))

    def set_approval(self, review_id: str, approved: bool, principal: str) -> None:
        self._require_results()
        self._migrate_legacy_sqlite()
        self.approvals.update_one(
            {"_id": review_id},
            {"$set": {
                "approved": approved,
                "approved_by": principal,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    def enqueue(self, draft: EmailDraft) -> tuple[EmailResult, bool]:
        results = self._require_results()
        self._migrate_legacy_sqlite()
        now = datetime.now(timezone.utc)
        result = EmailResult(
            email_id=uuid4(),
            lead_id=draft.lead_id,
            review_id=draft.review_id,
            draft_key=draft.draft_key,
            business_name=draft.business_name,
            recipient=draft.recipient,
            sender=draft.sender,
            proposal_file=draft.proposal_file,
            status="pending",
            created_at=now,
        )
        document = result.model_dump(mode="python")
        document["email_id"] = str(result.email_id)
        document["_id"] = str(result.email_id)
        try:
            results.insert_one(document)
            return result, True
        except Exception as exc:
            if getattr(exc, "code", None) != 11000:
                raise

        retried = results.find_one_and_update(
            {"review_id": draft.review_id, "status": {"$in": ["failed", "uncertain"]}},
            {"$set": {
                "status": "pending",
                "error": None,
                "sent_at": None,
                "message_id": None,
            }},
            return_document=True,
        )
        if retried is not None:
            return self._result(retried), True
        existing = results.find_one({"review_id": draft.review_id})
        stored = self._result(existing)
        if stored is None:
            raise RuntimeError("Email review record disappeared during enqueue.")
        return stored, False

    def record_failure(self, lead_id: str, error: str) -> EmailResult:
        results = self._require_results()
        result = EmailResult(
            email_id=uuid4(),
            lead_id=lead_id,
            status="failed",
            created_at=datetime.now(timezone.utc),
            error=error,
        )
        document = result.model_dump(mode="python")
        document["email_id"] = str(result.email_id)
        document["_id"] = str(result.email_id)
        results.insert_one(document)
        return result

    def get(self, email_id: UUID | str) -> EmailResult | None:
        results = self._require_results()
        self._migrate_legacy_sqlite()
        return self._result(results.find_one({"_id": str(email_id)}))

    def list_records(
        self, *, status: str | None = None, limit: int = 25, offset: int = 0,
    ) -> tuple[list[EmailResult], int]:
        results = self._require_results()
        self._migrate_legacy_sqlite()
        query = {"status": status} if status is not None else {}
        total = results.count_documents(query)
        cursor = (
            results.find(query)
            .sort([("created_at", -1), ("_id", 1)])
            .skip(offset)
            .limit(limit)
        )
        return [self._result(document) for document in cursor], total

    def claim(self, email_id: UUID | str) -> EmailResult | None:
        results = self._require_results()
        document = results.find_one_and_update(
            {"_id": str(email_id), "status": "pending"},
            {"$set": {"status": "sending"}},
            return_document=True,
        )
        return self._result(document)

    def finish(
        self, email_id: UUID | str, status: str, error: str | None = None,
        message_id: str | None = None,
    ) -> None:
        results = self._require_results()
        sent_at = datetime.now(timezone.utc) if status == "sent" else None
        results.update_one(
            {"_id": str(email_id), "status": "sending"},
            {"$set": {
                "status": status,
                "sent_at": sent_at,
                "message_id": message_id,
                "error": error,
            }},
        )
