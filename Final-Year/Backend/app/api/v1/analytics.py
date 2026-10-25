import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pymongo.errors import PyMongoError

from app.core.config import get_email_settings
from app.schemas.analytics import AnalyticsActivity, AnalyticsLead, AnalyticsOverview
from app.services.email_results import EmailResultStore
from app.services.lead_results import LeadResultStore
from app.services.outreach_repository import DispatchLedger

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview() -> AnalyticsOverview:
    """Return live aggregate metrics and recent activity from MongoDB."""
    try:
        # Analytics reads email history too, so use the settings model that
        # includes the email store's legacy migration path.
        settings = get_email_settings()
        leads = LeadResultStore(settings.lead_json_path)
        leads.list_records(limit=10, offset=0)
        lead_collection = leads.collection
        if lead_collection is None:
            raise RuntimeError("MongoDB must be configured to load analytics.")
        lead_query: dict[str, object] = {}
        high_priority = {"data.scoring.priority": {"$regex": "^High$", "$options": "i"}}
        qualified = {"data.scoring.qualification_status": {"$regex": "^Qualified$", "$options": "i"}}
        has_website = {
            "data.discovery.website": {
                "$exists": True,
                "$nin": [None, ""],
            },
        }

        lead_documents = list(
            lead_collection.find({}, {"data": 1, "updated_at": 1})
            .sort("updated_at", -1)
            .limit(10)
        )
        recent_leads = []
        for document in lead_documents:
            data = document["data"]
            discovery = data["discovery"]
            scoring = data["scoring"]
            recent_leads.append(AnalyticsLead(
                lead_id=str(data["lead_id"]),
                business_name=discovery["business_name"],
                category=discovery.get("category"),
                lead_score=scoring.get("lead_score"),
                priority=scoring.get("priority", "Unknown"),
                updated_at=document.get("updated_at"),
            ))

        emails = EmailResultStore(settings.email_db_path)
        emails.list_records(limit=5)
        email_collection = emails.results
        if email_collection is None:
            raise RuntimeError("MongoDB must be configured to load analytics.")
        email_documents = list(
            email_collection.find({}, {"email_id": 1, "business_name": 1, "status": 1, "created_at": 1})
            .sort([("created_at", -1), ("_id", 1)])
            .limit(5)
        )
        recent_emails = [AnalyticsActivity(
            id=str(item.get("email_id", item["_id"])),
            label=item.get("business_name") or "Proposal email",
            status=str(item["status"]),
            created_at=item.get("created_at"),
        ) for item in email_documents]

        calls = DispatchLedger(settings.eligibility_db_path)
        calls.list_records(limit=5)
        call_collection = calls.collection
        if call_collection is None:
            raise RuntimeError("MongoDB must be configured to load analytics.")
        call_documents = list(
            call_collection.find({}, {"idempotency_key": 1, "lead_id": 1, "status": 1, "created_at": 1})
            .sort([("created_at", -1), ("_id", 1)])
            .limit(5)
        )
        recent_calls = [AnalyticsActivity(
            id=str(item.get("idempotency_key", item["_id"])),
            label=str(item.get("lead_id", "Outbound call")),
            status=str(item["status"]),
            created_at=item.get("created_at"),
        ) for item in call_documents]

        return AnalyticsOverview(
            generated_at=datetime.now(timezone.utc),
            leads_total=lead_collection.count_documents(lead_query),
            high_priority_leads=lead_collection.count_documents(high_priority),
            qualified_leads=lead_collection.count_documents(qualified),
            websites_total=lead_collection.count_documents(has_website),
            emails_total=email_collection.count_documents({}),
            emails_sent=email_collection.count_documents({"status": "sent"}),
            calls_total=call_collection.count_documents({}),
            calls_dispatched=call_collection.count_documents({"status": "dispatched"}),
            recent_leads=recent_leads,
            recent_emails=recent_emails,
            recent_calls=recent_calls,
        )
    except (
        PyMongoError,
        sqlite3.Error,
        OSError,
        RuntimeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "analytics_data_unavailable"},
        ) from None
