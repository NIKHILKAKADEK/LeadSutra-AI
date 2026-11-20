from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.agents.lead_pipeline.pipeline import canonical_lead_output
from app.services.lead_results import LeadResultStore
from tests.test_lead_discovery import business, enriched


class Cursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, *_args):
        return self

    def skip(self, count):
        self.documents = self.documents[count:]
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self):
        self.documents = {}

    def find_one(self, query, *_args):
        return self.documents.get(query["_id"])

    def update_one(self, query, update, upsert=False):
        current = self.documents.setdefault(query["_id"], {}) if upsert else self.documents.get(query["_id"])
        if current is None:
            return
        current.update(update.get("$setOnInsert", {}))
        current.update(update.get("$set", {}))

    def insert_one(self, document):
        self.documents[document["_id"]] = document

    def count_documents(self, _query):
        return len(self.documents)

    def find(self, *_args):
        return Cursor(self.documents.values())


class MongoLeadResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "legacy-results"
        self.collections = {
            "leads": Collection(),
            "lead_runs": Collection(),
            "migrations": Collection(),
        }
        self.collection_patch = patch(
            "app.services.lead_results.get_mongo_collection",
            side_effect=lambda name: self.collections[name],
        )
        self.collection_patch.start()
        self.addCleanup(self.collection_patch.stop)
        self.store = LeadResultStore(self.root)

    def test_saved_results_and_run_snapshot_are_in_mongodb_only(self):
        lead = canonical_lead_output(enriched(business(0, business_name="Mongo prospect")))
        run_id = self.store.save([lead])

        self.assertTrue(run_id)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.collections["leads"].documents[lead.lead_id]["data"]["discovery"]["business_name"],
                         "Mongo prospect")
        self.assertEqual(self.store.load(run_id)[0].lead_id, lead.lead_id)
        self.assertEqual(self.store.get_by_id(lead.lead_id).lead_id, lead.lead_id)
        page, count = self.store.list_records(q="Mongo")
        self.assertEqual(count, 1)
        self.assertEqual(page[0].lead_id, lead.lead_id)

    def test_missing_mongodb_fails_instead_of_falling_back_to_local_storage(self):
        with patch("app.services.lead_results.get_mongo_collection", return_value=None):
            store = LeadResultStore(self.root)
            with self.assertRaisesRegex(RuntimeError, "MongoDB must be configured"):
                store.save([])
        self.assertFalse(self.root.exists())

    def test_flat_legacy_mongodb_leads_are_migrated_for_listing(self):
        legacy = {
            "_id": "legacy-lead-1",
            "business_name": "Legacy Prospect",
            "category": "Gym",
            "address": "Nashik",
            "phone": "+91 9876543210",
            "website": "https://legacy.example",
            "google_place_id": "place-1",
            "source": "google_places",
            "data": None,
        }
        self.collections["leads"].documents[legacy["_id"]] = legacy

        records, total = self.store.list_records()

        self.assertEqual(total, 1)
        self.assertEqual(records[0].lead_id, "legacy-lead-1")
        self.assertEqual(records[0].discovery.business_name, "Legacy Prospect")
        self.assertEqual(records[0].enrichment.phone_numbers, ["+91 9876543210"])
        self.assertEqual(
            self.collections["leads"].documents["legacy-lead-1"]["data"]["scoring"]["priority"],
            "Unknown",
        )
        self.assertIn(
            "leads-mongodb-flat-v1",
            self.collections["migrations"].documents,
        )
