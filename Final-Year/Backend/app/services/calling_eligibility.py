from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.mongodb import get_mongo_collection

from app.schemas.calling_eligibility import (
    ConsentRecordInput, ConsentStatus, EligibilityResponse,
)
from app.models.leads import PreparedLead, normalize_indian_mobile



def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None

class CallingEligibilityStore:
    """MongoDB persistence for permission records."""

    def __init__(self, path: str | Path | None = None):
        self.legacy_path = Path(path) if path is not None and str(path) != ":memory:" else None
        self.collection = get_mongo_collection("consents")
        self.migrations = get_mongo_collection("migrations")

    def _require_collection(self) -> Any:
        if self.collection is None:
            raise RuntimeError("MongoDB must be configured to store consent records.")
        return self.collection

    def _migrate_legacy_sqlite(self) -> None:
        if (
            self.legacy_path is None
            or not self.legacy_path.is_file()
            or self.migrations is None
            or self.collection is None
        ):
            return
        marker = "consent-sqlite-v1"
        if self.migrations.find_one({"_id": marker}, {"_id": 1}):
            return

        uri = self.legacy_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            table_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='consent_records'"
            ).fetchone()
            if table_exists:
                for row in db.execute("SELECT * FROM consent_records"):
                    item = dict(row)
                    for field in ("recorded_at", "verified_at", "expiry_at", "revoked_at"):
                        if item.get(field):
                            item[field] = datetime.fromisoformat(item[field])
                    self.collection.update_one(
                        {"lead_id": item["lead_id"], "phone_number": item["phone_number"]},
                        {"$setOnInsert": item},
                        upsert=True,
                    )
        self.migrations.update_one(
            {"_id": marker},
            {"$setOnInsert": {"completed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def save_consent(self, record: ConsentRecordInput) -> None:
        collection = self._require_collection()
        self._migrate_legacy_sqlite()
        phone = normalize_indian_mobile(record.phone_number)
        values = record.model_dump(mode="python")
        values["phone_number"] = phone
        values["consent_status"] = record.consent_status.value
        collection.update_one(
            {"lead_id": record.lead_id, "phone_number": phone},
            {"$set": values},
            upsert=True,
        )

    def get_consent(self, lead_id: str, phone: str) -> dict | None:
        collection = self._require_collection()
        self._migrate_legacy_sqlite()
        record = collection.find_one(
            {"lead_id": lead_id, "phone_number": phone},
            {"_id": 0},
        )
        if record is not None:
            for field in ("recorded_at", "verified_at", "expiry_at", "revoked_at"):
                if isinstance(record.get(field), datetime):
                    record[field] = _iso(record[field])
        return record


def _reason_consent(record: dict | None, purpose: str, now: datetime) -> str | None:
    if record is None:
        return "consent_unknown"
    raw_status = record.get("consent_status")
    if raw_status is None:
        return "consent_unknown"
    try:
        status = ConsentStatus(raw_status)
    except (TypeError, ValueError):
        return "consent_unknown"
    if status == ConsentStatus.revoked or record.get("revoked_at"):
        return "consent_revoked"
    if status != ConsentStatus.verified:
        return "consent_" + status.value
    required_evidence = ("consent_scope", "consent_source", "evidence_reference", "verified_at", "verified_by")
    if not all(record.get(key) for key in required_evidence):
        return "consent_evidence_missing"
    scope = record.get("consent_scope")
    if not isinstance(scope, str) or not isinstance(purpose, str):
        return "consent_evidence_missing"
    if scope.casefold() != purpose.casefold():
        return "consent_purpose_mismatch"
    try:
        expiry = _datetime(record.get("expiry_at"))
    except (TypeError, ValueError):
        return "consent_expiry_invalid"
    if expiry and expiry <= now:
        return "consent_expired"
    return None


def check_consent(record: dict | None, purpose: str, now: datetime | None = None) -> tuple[bool, str | None]:
    """Evaluate consent independently; evidence values are never included in results."""
    reason = _reason_consent(record, purpose, now or datetime.now(timezone.utc))
    return reason is None, reason


def evaluate_eligibility(
    *, lead_id: str, phone_number: str, leads: list[PreparedLead], store: CallingEligibilityStore,
    purpose: str, now: datetime | None = None,
) -> EligibilityResponse:
    checked_at = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    try:
        phone = normalize_indian_mobile(phone_number)
    except ValueError:
        return EligibilityResponse(eligible=False, reason_codes=["phone_invalid"], checked_at=checked_at,
                                  lead_id=lead_id, normalized_phone_number=None)

    lead = next((item for item in leads if item.lead_id == lead_id), None)
    if lead is None:
        reasons.append("lead_not_found")
    else:
        valid_phones = {item.normalized_value for item in lead.phone_numbers}
        if phone not in valid_phones:
            reasons.append("phone_not_associated_with_lead")

    consent = store.get_consent(lead_id, phone)
    consent_ok, consent_reason = check_consent(consent, purpose, checked_at)
    if not consent_ok and consent_reason:
        reasons.append(consent_reason)
    return EligibilityResponse(eligible=not reasons, reason_codes=reasons, checked_at=checked_at,
                               lead_id=lead_id, normalized_phone_number=phone)
