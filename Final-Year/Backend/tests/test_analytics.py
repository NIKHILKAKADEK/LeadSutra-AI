from datetime import datetime, timezone
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from app.app import app
from app.api.v1.analytics import analytics_overview


class AnalyticsTests(unittest.TestCase):
    def test_analytics_overview_uses_live_counts_and_recent_records(self):
        self.assertIn("/api/v1/analytics/overview", app.openapi()["paths"])
        updated_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
        lead_collection = MagicMock()
        lead_collection.find.return_value.sort.return_value.limit.return_value = [{
            "data": {
                "lead_id": "lead-1",
                "discovery": {"business_name": "Acme", "category": "Technology"},
                "scoring": {"lead_score": 82.5, "priority": "High"},
            },
            "updated_at": updated_at,
        }]

        def lead_count(query):
            if not query:
                return 8
            if "data.scoring.priority" in query:
                return 3
            if "data.scoring.qualification_status" in query:
                return 4
            if "data.discovery.website" in query:
                return 6
            return 0

        lead_collection.count_documents.side_effect = lead_count
        email_collection = MagicMock()
        email_collection.find.return_value.sort.return_value.limit.return_value = [{
            "_id": "email-1",
            "email_id": "email-1",
            "business_name": "Acme",
            "status": "sent",
            "created_at": updated_at,
        }]
        email_collection.count_documents.side_effect = lambda query: (
            2 if query == {} else 1
        )
        call_collection = MagicMock()
        call_collection.find.return_value.sort.return_value.limit.return_value = [{
            "_id": "call-1",
            "idempotency_key": "call-1",
            "lead_id": "lead-1",
            "status": "dispatched",
            "created_at": updated_at,
        }]
        call_collection.count_documents.side_effect = lambda query: (
            3 if query == {} else 1
        )

        with ExitStack() as stack:
            stack.enter_context(patch(
                "app.api.v1.analytics.get_email_settings",
                return_value=SimpleNamespace(
                    lead_json_path=None,
                    email_db_path=None,
                    eligibility_db_path=None,
                ),
            ))
            stack.enter_context(patch(
                "app.api.v1.analytics.LeadResultStore",
                return_value=SimpleNamespace(
                    collection=lead_collection,
                    list_records=lambda **_: ([], 0),
                ),
            ))
            stack.enter_context(patch(
                "app.api.v1.analytics.EmailResultStore",
                return_value=SimpleNamespace(
                    results=email_collection,
                    list_records=lambda **_: ([], 0),
                ),
            ))
            stack.enter_context(patch(
                "app.api.v1.analytics.DispatchLedger",
                return_value=SimpleNamespace(
                    collection=call_collection,
                    list_records=lambda **_: ([], 0),
                ),
            ))
            result = analytics_overview()

        self.assertEqual((result.leads_total, result.high_priority_leads), (8, 3))
        self.assertEqual((result.qualified_leads, result.websites_total), (4, 6))
        self.assertEqual((result.emails_total, result.emails_sent), (2, 1))
        self.assertEqual((result.calls_total, result.calls_dispatched), (3, 1))
        self.assertEqual(result.recent_leads[0].lead_score, 82.5)
        self.assertEqual(result.recent_leads[0].business_name, "Acme")
        self.assertEqual(result.recent_emails[0].status, "sent")
        self.assertEqual(result.recent_calls[0].status, "dispatched")
