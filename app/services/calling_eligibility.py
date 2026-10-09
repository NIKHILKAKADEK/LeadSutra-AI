"""Consent and lead validation for outbound eligibility."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.calling_eligibility import (
    ConsentRecordInput, ConsentStatus, EligibilityResponse,
)
from app.models.leads import PreparedLead, normalize_indian_mobile



def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None

class CallingEligibilityStore:
    """SQLite persistence for permission records."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS consent_records (
                lead_id TEXT NOT NULL, phone_number TEXT NOT NULL, consent_status TEXT NOT NULL,
                consent_scope TEXT, consent_source TEXT, evidence_reference TEXT,
                recorded_at TEXT NOT NULL, verified_at TEXT, verified_by TEXT,
                expiry_at TEXT, revoked_at TEXT, PRIMARY KEY (lead_id, phone_number))""")
    def save_consent(self, record: ConsentRecordInput) -> None:
        phone = normalize_indian_mobile(record.phone_number)
        with self._connect() as db:
            db.execute("""INSERT INTO consent_records VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(lead_id, phone_number) DO UPDATE SET
                consent_status=excluded.consent_status, consent_scope=excluded.consent_scope,
                consent_source=excluded.consent_source, evidence_reference=excluded.evidence_reference,
                recorded_at=excluded.recorded_at, verified_at=excluded.verified_at,
                verified_by=excluded.verified_by, expiry_at=excluded.expiry_at,
                revoked_at=excluded.revoked_at""",
                (record.lead_id, phone, record.consent_status.value, record.consent_scope,
                 record.consent_source, record.evidence_reference, _iso(record.recorded_at),
                 _iso(record.verified_at), record.verified_by, _iso(record.expiry_at),
                 _iso(record.revoked_at)))

    def get_consent(self, lead_id: str, phone: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM consent_records WHERE lead_id=? AND phone_number=?",
                             (lead_id, phone)).fetchone()
        return dict(row) if row else None


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
        if (lead.qualification_status or "").strip().casefold() != "qualified":
            reasons.append("lead_not_qualified")

    consent = store.get_consent(lead_id, phone)
    consent_ok, consent_reason = check_consent(consent, purpose, checked_at)
    if not consent_ok and consent_reason:
        reasons.append(consent_reason)
    return EligibilityResponse(eligible=not reasons, reason_codes=reasons, checked_at=checked_at,
                               lead_id=lead_id, normalized_phone_number=phone)
