"""Eligibility-gated OmniDimension outbound dispatch with backend idempotency."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from omnidimension import APIError

from app.models.call_dispatch import (
    DispatchResult, DispatchStatus, LeadCallContext, OutboundCallContext,
    RepresentedBusinessContext,
)
from app.models.calling_eligibility import CheckStatus
from app.models.leads import LeadFileError, PreparedLead, normalize_indian_mobile
from app.services.calling_eligibility import CallingEligibilityStore, evaluate_eligibility
from app.services.leads import LeadJsonService
from app.services.omnidimension import OmniDimensionService
from app.services.voice_agent_configs import outbound_agent_config


class DispatchProvider(Protocol):
    def get_agent(self, agent_id: int) -> Any: ...
    def dispatch_call(self, agent_id: int, to_number: str, call_context: dict[str, Any]) -> Any: ...


class OmniDimensionDispatchProvider:
    """Thin adapter over verified methods in the installed OmniDimension SDK."""

    def __init__(self, api_key: str | None):
        self._client = OmniDimensionService(api_key).create_client()

    def get_agent(self, agent_id: int) -> Any:
        return self._client.agent.get(agent_id)

    def dispatch_call(self, agent_id: int, to_number: str, call_context: dict[str, Any]) -> Any:
        return self._client.call.dispatch_call(
            agent_id=agent_id,
            to_number=to_number,
            call_context=call_context,
        )


class DispatchLedger:
    """Durable idempotency ledger; a claimed key is never silently retried."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS call_dispatch_ledger (
                idempotency_key TEXT PRIMARY KEY,
                lead_id TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_request_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")

    def list_records(self, *, lead_id: str | None = None, status: str | None = None,
                     limit: int = 25, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        values: list[Any] = []
        if lead_id is not None:
            clauses.append("lead_id=?")
            values.append(lead_id)
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) FROM call_dispatch_ledger" + where, values).fetchone()[0]
            rows = db.execute("SELECT idempotency_key, lead_id, phone_number, status, provider_request_id, "
                              "created_at, updated_at FROM call_dispatch_ledger" + where +
                              " ORDER BY created_at DESC, idempotency_key LIMIT ? OFFSET ?",
                              [*values, limit, offset]).fetchall()
        return ([{"call_id": row[0], "lead_id": row[1], "phone_number": row[2],
                  "dispatch_status": row[3], "provider_request_id": row[4],
                  "created_at": row[5], "updated_at": row[6],
                  "dispatch_requested": row[3] in {DispatchStatus.dispatched.value,
                                                       DispatchStatus.provider_error.value,
                                                       DispatchStatus.uncertain.value},
                  "provider_accepted": row[3] == DispatchStatus.dispatched.value,
                  "call_outcome": "unknown"} for row in rows], total)

    def get_record(self, call_id: str) -> dict[str, Any] | None:
        # Use an exact query so detail lookup stays independent of pagination.
        with self._connect() as db:
            row = db.execute("SELECT idempotency_key, lead_id, phone_number, status, provider_request_id, "
                             "created_at, updated_at FROM call_dispatch_ledger WHERE idempotency_key=?",
                             (call_id,)).fetchone()
        if not row:
            return None
        return {"call_id": row[0], "lead_id": row[1], "phone_number": row[2],
                "dispatch_status": row[3], "provider_request_id": row[4],
                "created_at": row[5], "updated_at": row[6],
                "dispatch_requested": row[3] in {DispatchStatus.dispatched.value,
                                                   DispatchStatus.provider_error.value,
                                                   DispatchStatus.uncertain.value},
                "provider_accepted": row[3] == DispatchStatus.dispatched.value,
                "call_outcome": "unknown"}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def lookup(self, key: UUID | str) -> tuple[str, str, str | None] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT lead_id, phone_number, status FROM call_dispatch_ledger WHERE idempotency_key=?",
                (str(key),),
            ).fetchone()
        return (row[0], row[1], row[2]) if row else None

    def claim(self, key: UUID | str, lead_id: str, phone: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as db:
                db.execute("INSERT INTO call_dispatch_ledger VALUES (?,?,?,?,?,?,?)",
                           (str(key), lead_id, phone, "dispatching", None, now, now))
            return True
        except sqlite3.IntegrityError:
            return False

    def finish(self, key: UUID | str, status: DispatchStatus,
               provider_request_id: str | None = None) -> None:
        with self._connect() as db:
            db.execute("UPDATE call_dispatch_ledger SET status=?, provider_request_id=?, updated_at=? "
                       "WHERE idempotency_key=?",
                       (status.value, provider_request_id, datetime.now(timezone.utc).isoformat(), str(key)))


def _provider_payload(response: Any) -> Any:
    """Unwrap the documented SDK envelope without trusting arbitrary fields."""
    if isinstance(response, dict) and "json" in response:
        return response.get("json")
    return response


def _provider_request_id(response: Any) -> str | None:
    data = _provider_payload(response)
    if not isinstance(data, dict):
        return None
    request_id = data.get("requestId")
    return str(request_id) if request_id is not None else None


class CallDispatchService:
    def __init__(
        self,
        *,
        lead_service: LeadJsonService,
        eligibility_store: CallingEligibilityStore,
        ledger: DispatchLedger,
        provider_factory,
        agent_id: int | None,
        enabled: bool,
        purpose: str,
        represented_business_name: str | None = None,
        represented_business_identity_verified: bool = False,
    ):
        self._lead_service = lead_service
        self._eligibility_store = eligibility_store
        self._ledger = ledger
        self._provider_factory = provider_factory
        self._agent_id = agent_id
        self._enabled = enabled
        self._purpose = purpose
        self._represented_business_name = represented_business_name
        self._represented_business_identity_verified = represented_business_identity_verified
        self._agent_config = outbound_agent_config()

    def _blocked(self, lead_id: str, reason: str, phone: str | None = None) -> DispatchResult:
        return DispatchResult(status=DispatchStatus.blocked, eligible=False,
                              dispatch_enabled=self._enabled, lead_id=lead_id,
                              normalized_phone_number=phone, agent_id=self._agent_id,
                              reason_codes=[reason])

    def _prepare(self, lead_id: str, phone_number: str) -> tuple[PreparedLead, str] | DispatchResult:
        if not isinstance(self._agent_id, int) or isinstance(self._agent_id, bool) or self._agent_id <= 0:
            return self._blocked(lead_id, "outbound_agent_not_configured")
        try:
            phone = normalize_indian_mobile(phone_number)
        except (TypeError, ValueError):
            return self._blocked(lead_id, "phone_invalid")
        try:
            leads = self._lead_service.load()
        except LeadFileError:
            return self._blocked(lead_id, "lead_source_unavailable", phone)
        lead = next((item for item in leads if item.lead_id == lead_id), None)
        if lead is None:
            return self._blocked(lead_id, "lead_not_found", phone)
        if phone not in {entry.normalized_value for entry in lead.phone_numbers}:
            return self._blocked(lead_id, "phone_not_associated_with_lead", phone)
        if not self._purpose.strip():
            return self._blocked(lead_id, "outbound_purpose_not_configured", phone)
        return lead, phone

    def _call_context(self, lead: PreparedLead) -> dict[str, str]:
        """Build provider data from validated lead facts and configured identity only."""
        if not self._represented_business_identity_verified:
            raise ValueError("represented business identity is not verified")
        name = self._represented_business_name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("represented business identity is not configured")
        context = OutboundCallContext(
            lead=LeadCallContext(lead_business_name=lead.business_name),
            represented_business=RepresentedBusinessContext(verified_business_name=name),
            contact_basis_status="verified",
        )
        declared_variables = set(self._agent_config.get("dynamic_variables", {}))
        return context.to_provider_context(declared_variables)

    def _eligibility(self, lead_id: str, phone: str):
        operational = self._eligibility_store.get_operational_check(lead_id, phone)
        return evaluate_eligibility(
            lead_id=lead_id,
            phone_number=phone,
            leads=self._lead_service.load(),
            store=self._eligibility_store,
            purpose=self._purpose,
            calling_hours=CheckStatus(operational["calling_hours_status"]) if operational else CheckStatus.unknown,
            attempts_used=operational["attempts_used"] if operational else None,
            attempt_limit=operational["attempt_limit"] if operational else None,
            operational_checked_at=operational["checked_at"] if operational else None,
        )

    def run(self, lead_id: str, phone_number: str, idempotency_key: UUID) -> DispatchResult:
        prepared = self._prepare(lead_id, phone_number)
        if isinstance(prepared, DispatchResult):
            return prepared
        lead, phone = prepared

        try:
            eligibility = self._eligibility(lead_id, phone)
        except LeadFileError:
            return self._blocked(lead_id, "lead_source_unavailable", phone)
        if not eligibility.eligible:
            return DispatchResult(status=DispatchStatus.blocked, eligible=False,
                                  dispatch_enabled=self._enabled, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=eligibility.reason_codes)

        if not self._enabled:
            return DispatchResult(status=DispatchStatus.dry_run, eligible=True,
                                  dispatch_enabled=False, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=["provider_dispatch_disabled"])

        if (not self._represented_business_identity_verified or
                not isinstance(self._represented_business_name, str) or
                not self._represented_business_name.strip()):
            return self._blocked(lead_id, "represented_business_identity_unverified", phone)

        call_context = self._call_context(lead)

        previous = self._ledger.lookup(idempotency_key)
        if previous:
            if previous[0] != lead_id or previous[1] != phone:
                return DispatchResult(status=DispatchStatus.duplicate, eligible=True,
                                      dispatch_enabled=True, lead_id=lead_id,
                                      normalized_phone_number=phone, agent_id=self._agent_id,
                                      reason_codes=["idempotency_key_reused_for_different_call"])
            prior_status = previous[2]
            reason = ("previous_dispatch_outcome_uncertain" if prior_status == DispatchStatus.uncertain.value
                      else "duplicate_dispatch_key")
            return DispatchResult(status=DispatchStatus.duplicate, eligible=True,
                                  dispatch_enabled=True, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=[reason])

        try:
            provider: DispatchProvider = self._provider_factory()
            agent_response = _provider_payload(provider.get_agent(self._agent_id))
        except Exception:
            return self._blocked(lead_id, "provider_agent_verification_failed", phone)
        if not isinstance(agent_response, dict):
            return self._blocked(lead_id, "provider_agent_verification_failed", phone)
        try:
            live_agent_id = int(agent_response.get("id"))
        except (TypeError, ValueError):
            return self._blocked(lead_id, "provider_agent_verification_failed", phone)
        call_type = str(agent_response.get("bot_call_type", "")).casefold()
        if live_agent_id != self._agent_id or call_type not in {"outgoing", "outbound"}:
            return self._blocked(lead_id, "configured_agent_is_not_outbound", phone)
        raw_languages = agent_response.get("languages")
        if not isinstance(raw_languages, list):
            return self._blocked(lead_id, "agent_languages_unverified", phone)
        agent_languages = {
            str(item.get("label", "")).casefold() if isinstance(item, dict) else str(item).casefold()
            for item in raw_languages
        }
        configured_languages = self._agent_config.get("languages", [])
        if not isinstance(configured_languages, list) or any(
                not isinstance(language, str) or language.casefold() not in agent_languages
                for language in configured_languages):
            return self._blocked(lead_id, "agent_languages_unverified", phone)

        if not self._ledger.claim(idempotency_key, lead_id, phone):
            return DispatchResult(status=DispatchStatus.duplicate, eligible=True,
                                  dispatch_enabled=True, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=["duplicate_dispatch_key"])

        # Refresh every consent, suppression, telecom, hours, and attempts check
        # after agent verification and directly before the provider call.
        try:
            eligibility = self._eligibility(lead_id, phone)
        except LeadFileError:
            eligibility = None
        if eligibility is None or not eligibility.eligible:
            reasons = eligibility.reason_codes if eligibility else ["lead_source_unavailable"]
            self._ledger.finish(idempotency_key, DispatchStatus.blocked)
            return DispatchResult(status=DispatchStatus.blocked, eligible=False,
                                  dispatch_enabled=True, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=reasons)

        try:
            response = provider.dispatch_call(
                agent_id=self._agent_id,
                to_number=phone,
                call_context=call_context,
            )
        except APIError as exc:
            # The SDK maps transport failures to status_code 0. Such a result
            # may have reached the provider; record it and refuse automatic retry.
            uncertain = getattr(exc, "status_code", None) == 0
            result_status = DispatchStatus.uncertain if uncertain else DispatchStatus.provider_error
            self._ledger.finish(idempotency_key, result_status)
            return DispatchResult(status=result_status, eligible=True,
                                  dispatch_enabled=True, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=["provider_outcome_uncertain" if uncertain else "provider_rejected_dispatch"])
        except Exception:
            self._ledger.finish(idempotency_key, DispatchStatus.uncertain)
            return DispatchResult(status=DispatchStatus.uncertain, eligible=True,
                                  dispatch_enabled=True, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  reason_codes=["provider_outcome_uncertain"])

        data = _provider_payload(response)
        if isinstance(data, dict) and data.get("success") is True and data.get("status") == "dispatched":
            request_id = _provider_request_id(response)
            self._ledger.finish(idempotency_key, DispatchStatus.dispatched, request_id)
            return DispatchResult(status=DispatchStatus.dispatched, eligible=True,
                                  dispatched=True, dispatch_enabled=True, lead_id=lead_id,
                                  normalized_phone_number=phone, agent_id=self._agent_id,
                                  provider_request_id=request_id)

        # Any malformed/ambiguous success body might still represent a placed call.
        self._ledger.finish(idempotency_key, DispatchStatus.uncertain)
        return DispatchResult(status=DispatchStatus.uncertain, eligible=True,
                              dispatch_enabled=True, lead_id=lead_id,
                              normalized_phone_number=phone, agent_id=self._agent_id,
                              reason_codes=["provider_outcome_uncertain"])
