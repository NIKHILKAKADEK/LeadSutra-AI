from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4
from typing import Any

from pydantic import TypeAdapter

from app.agents.lead_pipeline.schema import LeadResult
from app.database.mongodb import get_mongo_collection


_LEAD_RESULTS = TypeAdapter(list[LeadResult])
_CREDENTIAL_FIELDS = {
    "api_key", "apikey", "password", "secret", "secret_key", "access_token",
    "refresh_token", "client_secret", "private_key", "authorization", "credentials",
    "x_api_key", "x_goog_api_key",
}


def _ensure_no_credentials(value: object) -> None:
    """Reject credential fields or URL credentials rather than saving them."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.casefold().replace("-", "_") in _CREDENTIAL_FIELDS:
                raise ValueError("Lead results must not contain credential fields.")
            _ensure_no_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _ensure_no_credentials(item)
    elif isinstance(value, str):
        try:
            url = urlsplit(value)
        except ValueError:
            return
        if url.scheme.lower() in {"http", "https"} and url.netloc:
            if url.username is not None or any(
                key.casefold().replace("-", "_") in _CREDENTIAL_FIELDS
                for key, _ in parse_qsl(url.query)
            ):
                raise ValueError("Lead results must not contain URL credentials.")


class LeadResultStore:
    """Persist and read canonical lead results exclusively through MongoDB."""

    def __init__(self, root: str | Path | None = None):
        self.root = (
            Path(root) if root is not None
            else Path(__file__).resolve().parents[1] / "results" / "leads"
        ).resolve()
        self.collection = get_mongo_collection("leads")
        self.runs = get_mongo_collection("lead_runs")
        self.migrations = get_mongo_collection("migrations")

    def _require_collection(self) -> Any:
        if self.collection is None or self.runs is None:
            raise RuntimeError("MongoDB must be configured to store lead results.")
        return self.collection

    def _migrate_local_results(self) -> None:
        """Import legacy JSON lead runs once; new results are never written to disk."""
        if self.collection is None or self.migrations is None:
            return
        marker_id = "leads-json-v1"
        if self.migrations.find_one({"_id": marker_id}, {"_id": 1}):
            return

        if self.root.is_file():
            paths = [self.root]
        elif self.root.is_dir():
            paths = sorted(
                (path for path in self.root.glob("*/leads.json")
                 if not path.parent.name.startswith(".")),
                key=lambda path: (path.stat().st_mtime_ns, str(path)),
                reverse=True,
            )
        else:
            paths = []

        for path in paths:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            for lead in self._load_path(path):
                self.collection.update_one(
                    {"_id": lead.lead_id},
                    {
                        "$setOnInsert": {
                            "data": lead.model_dump(mode="json"),
                            "created_at": modified,
                            "updated_at": modified,
                        }
                    },
                    upsert=True,
                )
        self.migrations.update_one(
            {"_id": marker_id},
            {"$setOnInsert": {"completed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def _migrate_legacy_mongodb_records(self) -> None:
        """Wrap older flat Mongo lead documents in the current canonical contract."""
        collection = self._require_collection()
        marker_id = "leads-mongodb-flat-v1"
        if (
            self.migrations is not None
            and self.migrations.find_one({"_id": marker_id}, {"_id": 1})
        ):
            return
        for document in collection.find({"data": None}):
            if isinstance(document.get("data"), dict):
                continue
            business_name = document.get("business_name")
            if not isinstance(business_name, str) or not business_name.strip():
                raise ValueError(
                    "A legacy MongoDB lead is missing its business name."
                )

            lead_id = str(document["_id"])
            discovery = {
                "lead_id": lead_id,
                "business_name": business_name,
                "category": document.get("category"),
                "address": document.get("address"),
                "phone": document.get("phone"),
                "email": document.get("email"),
                "website": document.get("website"),
                "latitude": document.get("latitude"),
                "longitude": document.get("longitude"),
                "rating": document.get("rating"),
                "review_count": document.get("review_count"),
                "place_id": document.get("google_place_id"),
                "discovery_source": document.get("source"),
            }
            enrichment = {
                "website_status": "not_checked",
                "website_url": document.get("website"),
                "emails": [document["email"]] if document.get("email") else [],
                "phone_numbers": [document["phone"]] if document.get("phone") else [],
            }
            scoring = {
                "lead_score": document.get("lead_score"),
                "priority": document.get("priority") or "Unknown",
                "qualification_status": (
                    document.get("qualification_status") or "Unknown"
                ),
            }
            lead = LeadResult.model_validate({
                "lead_id": lead_id,
                "discovery": discovery,
                "enrichment": enrichment,
                "scoring": scoring,
            })
            payload = lead.model_dump(mode="json")
            _ensure_no_credentials(payload)
            collection.update_one(
                {"_id": document["_id"], "data": None},
                {"$set": {"data": payload}},
            )
        if self.migrations is not None:
            self.migrations.update_one(
                {"_id": marker_id},
                {"$setOnInsert": {"completed_at": datetime.now(timezone.utc)}},
                upsert=True,
            )

    def save(self, leads: list[LeadResult]) -> str:
        """Validate and persist a discovery run and its canonical leads."""
        collection = self._require_collection()
        if self.runs is None:
            raise RuntimeError("MongoDB lead-runs collection is unavailable.")
        validated = _LEAD_RESULTS.validate_python([
            lead.model_dump(mode="python", warnings=False) if isinstance(lead, LeadResult) else lead
            for lead in leads
        ])
        payload = _LEAD_RESULTS.dump_python(validated, mode="json")
        _ensure_no_credentials(payload)

        now = datetime.now(timezone.utc)
        run_id = uuid4().hex
        for lead in payload:
            lead_id = lead["lead_id"]
            collection.update_one(
                {"_id": lead_id},
                {
                    "$set": {"data": lead, "updated_at": now, "latest_run_id": run_id},
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        self.runs.insert_one({
            "_id": run_id,
            "lead_ids": [lead["lead_id"] for lead in payload],
            "leads": payload,
            "created_at": now,
        })
        return run_id

    def load(self, run_id: str | UUID) -> list[LeadResult]:
        """Read a validated snapshot by its generated MongoDB run ID."""
        if self.runs is None:
            raise RuntimeError("MongoDB lead-runs collection is unavailable.")
        document = self.runs.find_one({"_id": UUID(str(run_id)).hex}, {"leads": 1})
        if document is None:
            return []
        leads = _LEAD_RESULTS.validate_python(document["leads"])
        _ensure_no_credentials(_LEAD_RESULTS.dump_python(leads, mode="json"))
        return leads

    def get_by_id(self, lead_id: str) -> LeadResult | None:
        """Return the newest saved canonical lead matching its stable ID."""
        collection = self._require_collection()
        self._migrate_legacy_mongodb_records()
        self._migrate_local_results()
        document = collection.find_one({"_id": lead_id}, {"data": 1})
        if document is None:
            return None
        lead = LeadResult.model_validate(document["data"])
        _ensure_no_credentials(lead.model_dump(mode="json"))
        return lead

    @staticmethod
    def _load_path(path: Path) -> list[LeadResult]:
        leads = _LEAD_RESULTS.validate_json(path.read_text(encoding="utf-8-sig"))
        _ensure_no_credentials(_LEAD_RESULTS.dump_python(leads, mode="json"))
        return leads

    def list_all_records(self) -> list[LeadResult]:
        """Load the current canonical snapshot for each lead from MongoDB."""
        collection = self._require_collection()
        self._migrate_legacy_mongodb_records()
        self._migrate_local_results()
        documents = collection.find({}, {"data": 1}).sort("updated_at", -1)
        return [LeadResult.model_validate(document["data"]) for document in documents]

    def list_records(
        self, *, q: str | None = None, category: str | None = None,
        qualification_status: str | None = None, priority: str | None = None,
        limit: int = 25, offset: int = 0,
    ) -> tuple[list[LeadResult], int]:
        """Search saved canonical snapshots, newest lead updates first."""
        collection = self._require_collection()
        self._migrate_legacy_mongodb_records()
        self._migrate_local_results()
        query: dict[str, object] = {}
        for field, value in (
            ("data.discovery.category", category),
            ("data.scoring.qualification_status", qualification_status),
            ("data.scoring.priority", priority),
        ):
            if value is not None:
                query[field] = {
                    "$regex": f"^{re.escape(value.strip())}$",
                    "$options": "i",
                }
        search = (q or "").strip()
        if search:
            expression = {"$regex": re.escape(search), "$options": "i"}
            query["$or"] = [
                {field: expression}
                for field in (
                    "data.discovery.business_name",
                    "data.discovery.address",
                    "data.discovery.category",
                    "data.discovery.phone",
                    "data.discovery.website",
                    "data.enrichment.website_url",
                    "data.enrichment.phone_numbers",
                )
            ]
        total = collection.count_documents(query)
        documents = collection.find(query, {"_id": 0, "data": 1})
        documents = documents.sort("updated_at", -1).skip(offset).limit(limit)
        leads = [LeadResult.model_validate(document["data"]) for document in documents]
        return leads, total
