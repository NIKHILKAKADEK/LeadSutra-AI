from __future__ import annotations

import re
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from app.agents.email.schema import EmailDraft
from app.agents.voice.schema import ProposalResult
from app.schemas.calling_eligibility import ConsentRecordInput
from app.schemas.outreach import DispatchStatus
from app.services.calling_eligibility import CallingEligibilityStore
from app.services.email_results import EmailResultStore
from app.services.outreach_repository import DispatchLedger
from app.services.proposals import ProposalJsonService
from app.services.research_outputs import ResearchOutputService


class DuplicateKeyError(Exception):
    code = 11000


def _value(document, dotted_key):
    value = document
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(document, query):
    for key, expected in query.items():
        actual = _value(document, key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$regex" in expected:
                options = re.IGNORECASE if expected.get("$options") == "i" else 0
                values = actual if isinstance(actual, list) else [actual]
                if not any(
                    value is not None and re.search(expected["$regex"], str(value), options)
                    for value in values
                ):
                    return False
            if "$in" not in expected and "$regex" not in expected and actual != expected:
                return False
        elif actual != expected:
            return False
    return True


class MemoryCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, keys, direction=None):
        if isinstance(keys, str):
            keys = [(keys, direction or 1)]
        for key, order in reversed(keys):
            self.documents.sort(
                key=lambda item: _value(item, key) or "",
                reverse=order < 0,
            )
        return self

    def skip(self, count):
        self.documents = self.documents[count:]
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class MemoryCollection:
    def __init__(self):
        self.documents = {}

    def _find(self, query):
        return next((item for item in self.documents.values() if _matches(item, query)), None)

    def find_one(self, query, projection=None):
        document = self._find(query)
        if document is None or projection is None:
            return document
        if any(value for value in projection.values()):
            return {key: _value(document, key) for key, include in projection.items() if include and _value(document, key) is not None}
        return {key: value for key, value in document.items() if not projection.get(key)}

    def insert_one(self, document):
        candidate = dict(document)
        key = candidate.setdefault("_id", str(uuid4()))
        if key in self.documents:
            raise DuplicateKeyError()
        review_id = candidate.get("review_id")
        if review_id and self._find({"review_id": review_id}):
            raise DuplicateKeyError()
        self.documents[key] = candidate

    def update_one(self, query, update, upsert=False):
        document = self._find(query)
        inserted = document is None
        if inserted:
            if not upsert:
                return
            document = {
                key: value for key, value in query.items()
                if not isinstance(value, dict)
            }
            key = document.setdefault("_id", str(uuid4()))
            self.documents[key] = document
        if inserted:
            document.update(update.get("$setOnInsert", {}))
        document.update(update.get("$set", {}))

    def find_one_and_update(self, query, update, return_document=False):
        document = self._find(query)
        if document is None:
            return None
        document.update(update.get("$set", {}))
        return document

    def find(self, query=None, projection=None):
        query = query or {}
        docs = [doc for doc in self.documents.values() if _matches(doc, query)]
        if projection:
            docs = [self.find_one({"_id": doc["_id"]}, projection) for doc in docs]
        return MemoryCursor(docs)

    def count_documents(self, query):
        return sum(1 for document in self.documents.values() if _matches(document, query))


class MongoPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.collections = {}

        def get_collection(name):
            return self.collections.setdefault(name, MemoryCollection())

        self.patches = [
            patch(f"{module}.get_mongo_collection", side_effect=get_collection)
            for module in (
                "app.services.email_results",
                "app.services.outreach_repository",
                "app.services.calling_eligibility",
                "app.services.proposals",
                "app.services.research_outputs",
            )
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_email_approval_and_delivery_state_transitions_are_persisted(self):
        store = EmailResultStore()
        draft = EmailDraft(
            lead_id="lead-1",
            business_name="Example",
            recipient="buyer@example.com",
            sender="seller@example.com",
            proposal_file="lead-1/proposal.json",
            subject="Hello",
            body="Message",
            review_id="a" * 64,
        )
        queued, created = store.enqueue(draft)
        duplicate, created_again = store.enqueue(draft)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(queued.email_id, duplicate.email_id)
        store.set_approval(draft.review_id, True, "admin")
        self.assertTrue(store.approved(draft.review_id))
        self.assertEqual(store.claim(queued.email_id).status, "sending")
        store.finish(queued.email_id, "sent", message_id="fixture-message")
        self.assertEqual(store.get(queued.email_id).status, "sent")
        rows, total = store.list_records(status="sent")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].message_id, "fixture-message")

    def test_dispatch_idempotency_and_consent_records_use_mongodb(self):
        key = uuid4()
        ledger = DispatchLedger()
        self.assertTrue(ledger.claim(key, "lead-1", "+919876543210"))
        self.assertFalse(ledger.claim(key, "lead-1", "+919876543210"))
        ledger.finish(key, DispatchStatus.dispatched, "provider-id")
        self.assertEqual(ledger.lookup(key), ("lead-1", "+919876543210", "dispatched"))
        history, count = ledger.list_records(lead_id="lead-1")
        self.assertEqual(count, 1)
        self.assertTrue(history[0]["provider_accepted"])

        consent = CallingEligibilityStore()
        consent.save_consent(ConsentRecordInput(
            lead_id="lead-1",
            phone_number="+919876543210",
            consent_status="verified",
            consent_scope="commercial_sales_call",
            consent_source="fixture",
            evidence_reference="fixture:permission",
            recorded_at=datetime.now(timezone.utc),
            verified_at=datetime.now(timezone.utc),
            verified_by="admin",
        ))
        record = consent.get_consent("lead-1", "+919876543210")
        self.assertEqual(record["consent_status"], "verified")
        self.assertEqual(record["consent_source"], "fixture")

    def test_proposals_and_research_are_saved_and_loaded_from_mongodb(self):
        root = Path(self.temp.name)
        proposals = ProposalJsonService(root / "proposals")
        proposal = ProposalResult(lead_id="lead-1", proposed_service="Fixture service")
        proposals.save("lead-1", proposal, {"summary": "Fixture summary"})
        self.assertFalse((root / "proposals").exists())
        self.assertEqual(proposals.load("lead-1"), proposal)
        self.assertEqual(proposals.load_rich("lead-1"), {"summary": "Fixture summary"})

        research = ResearchOutputService(root / "research")
        payload = {"business_summary": "Fixture research"}
        research.save("lead-1", payload)
        self.assertFalse((root / "research").exists())
        self.assertEqual(research.load("lead-1"), payload)
        competitor_payload = {"status": "complete", "competitors": [{"name": "Fixture Gym"}]}
        research.save_competitors("lead-1", competitor_payload)
        self.assertEqual(research.load_competitors("lead-1"), competitor_payload)

    def test_old_sqlite_consent_rows_are_imported_without_sqlite_writes(self):
        database = Path(self.temp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("""CREATE TABLE consent_records (
                lead_id TEXT NOT NULL, phone_number TEXT NOT NULL, consent_status TEXT NOT NULL,
                consent_scope TEXT, consent_source TEXT, evidence_reference TEXT,
                recorded_at TEXT NOT NULL, verified_at TEXT, verified_by TEXT,
                expiry_at TEXT, revoked_at TEXT, PRIMARY KEY (lead_id, phone_number))""")
            connection.execute(
                "INSERT INTO consent_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("lead-1", "+919876543210", "verified", "purpose", "fixture",
                 "evidence", "2026-10-14T00:00:00+00:00", None, None, None, None),
            )
        before = database.read_bytes()
        migrated = CallingEligibilityStore(database).get_consent("lead-1", "+919876543210")
        self.assertEqual(migrated["consent_status"], "verified")
        self.assertEqual(database.read_bytes(), before)
