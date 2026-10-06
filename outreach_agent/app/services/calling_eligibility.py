"""Fail-closed consent, suppression, and outbound eligibility checks."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models.calling_eligibility import (
    CheckStatus, ConsentRecordInput, ConsentStatus, EligibilityResponse,
    SuppressionInput, SuppressionStatus,
)
from app.models.leads import PreparedLead, normalize_indian_mobile

CHECK_FRESHNESS_SECONDS = 300


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _fresh(value: str | None, now: datetime) -> bool:
    checked_at = _datetime(value)
    if checked_at is None:
        return False
    age = (now - checked_at).total_seconds()
    return -60 <= age <= CHECK_FRESHNESS_SECONDS


class CallingEligibilityStore:
    """SQLite persistence for permission and suppression records."""

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
            db.execute("""CREATE TABLE IF NOT EXISTS suppression_records (
                phone_number TEXT PRIMARY KEY, suppression_status TEXT NOT NULL,
                reason TEXT, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS telecom_checks (
                lead_id TEXT NOT NULL, phone_number TEXT NOT NULL,
                preference_status TEXT NOT NULL, route_status TEXT NOT NULL,
                provider_reference TEXT, checked_at TEXT NOT NULL,
                PRIMARY KEY (lead_id, phone_number))""")
            db.execute("""CREATE TABLE IF NOT EXISTS operational_checks (
                lead_id TEXT NOT NULL, phone_number TEXT NOT NULL, calling_hours_status TEXT NOT NULL,
                attempts_used INTEGER, attempt_limit INTEGER, checked_at TEXT NOT NULL,
                PRIMARY KEY (lead_id, phone_number))""")

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

    def save_suppression(self, record: SuppressionInput) -> None:
        phone = normalize_indian_mobile(record.phone_number)
        with self._connect() as db:
            db.execute("""INSERT INTO suppression_records VALUES (?,?,?,?)
                ON CONFLICT(phone_number) DO UPDATE SET
                suppression_status=excluded.suppression_status, reason=excluded.reason,
                updated_at=excluded.updated_at""",
                (phone, record.suppression_status.value, record.reason, _iso(datetime.now(timezone.utc))))

    def get_suppression(self, phone: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM suppression_records WHERE phone_number=?", (phone,)).fetchone()
        return dict(row) if row else None

    def save_telecom_checks(self, lead_id: str, phone: str, preference: CheckStatus,
                            route: CheckStatus, provider_reference: str | None) -> None:
        phone = normalize_indian_mobile(phone)
        with self._connect() as db:
            db.execute("""INSERT INTO telecom_checks VALUES (?,?,?,?,?,?)
                ON CONFLICT(lead_id, phone_number) DO UPDATE SET
                preference_status=excluded.preference_status, route_status=excluded.route_status,
                provider_reference=excluded.provider_reference, checked_at=excluded.checked_at""",
                (lead_id, phone, preference.value, route.value, provider_reference,
                 datetime.now(timezone.utc).isoformat()))

    def get_telecom_checks(self, lead_id: str, phone: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM telecom_checks WHERE lead_id=? AND phone_number=?",
                             (lead_id, phone)).fetchone()
        return dict(row) if row else None

    def save_operational_check(self, lead_id: str, phone: str, calling_hours: CheckStatus,
                               attempts_used: int | None, attempt_limit: int | None) -> None:
        phone = normalize_indian_mobile(phone)
        with self._connect() as db:
            db.execute("""INSERT INTO operational_checks VALUES (?,?,?,?,?,?)
                ON CONFLICT(lead_id, phone_number) DO UPDATE SET
                calling_hours_status=excluded.calling_hours_status, attempts_used=excluded.attempts_used,
                attempt_limit=excluded.attempt_limit, checked_at=excluded.checked_at""",
                (lead_id, phone, calling_hours.value, attempts_used, attempt_limit,
                 datetime.now(timezone.utc).isoformat()))

    def get_operational_check(self, lead_id: str, phone: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM operational_checks WHERE lead_id=? AND phone_number=?",
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
    purpose: str, telecom_preference: CheckStatus = CheckStatus.unknown,
    calling_route: CheckStatus = CheckStatus.unknown, calling_hours: CheckStatus = CheckStatus.unknown,
    attempts_used: int | None = None, attempt_limit: int | None = None,
    operational_checked_at: str | None = None,
    now: datetime | None = None,
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
    suppression = store.get_suppression(phone)
    if suppression is None:
        reasons.append("suppression_unknown")
    elif suppression["suppression_status"] == SuppressionStatus.suppressed.value:
        reasons.append("phone_suppressed")
    elif suppression["suppression_status"] != SuppressionStatus.not_suppressed.value:
        reasons.append("suppression_unknown")

    telecom = store.get_telecom_checks(lead_id, phone)
    telecom_fresh = bool(telecom and _fresh(telecom.get("checked_at"), checked_at))
    pref = telecom_preference if telecom_preference != CheckStatus.unknown else (
        CheckStatus(telecom["preference_status"]) if telecom_fresh else CheckStatus.unknown)
    route = calling_route if calling_route != CheckStatus.unknown else (
        CheckStatus(telecom["route_status"]) if telecom_fresh else CheckStatus.unknown)
    if pref != CheckStatus.approved:
        reasons.append("telecom_preference_unverified")
    if route != CheckStatus.approved:
        reasons.append("calling_route_unapproved")
    operational_fresh = _fresh(operational_checked_at, checked_at)
    if calling_hours != CheckStatus.approved or not operational_fresh:
        reasons.append("calling_hours_unverified")
    if attempts_used is None or attempt_limit is None or attempt_limit <= 0 or not operational_fresh:
        reasons.append("attempt_limit_unverified")
    elif attempts_used >= attempt_limit:
        reasons.append("attempt_limit_reached")

    return EligibilityResponse(eligible=not reasons, reason_codes=reasons, checked_at=checked_at,
                               lead_id=lead_id, normalized_phone_number=phone)
