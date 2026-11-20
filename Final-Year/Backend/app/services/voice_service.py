from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from omnidimension import APIError

from app.core.config import get_settings
from app.integrations.omnidimension import OmniDimensionDispatchProvider
from app.models.leads import normalize_indian_mobile
from app.schemas.outreach import DispatchResult, DispatchStatus, VoiceCallRequest
from app.services.outreach_repository import DispatchLedger


class DispatchProvider(Protocol):
    def dispatch_call(self, agent_id: int, to_number: str) -> Any: ...


def _provider_payload(response: Any) -> Any:
    """Unwrap the SDK response envelope used by OmniDimension."""
    if isinstance(response, dict) and "json" in response:
        return response.get("json")
    return response


def _request_id(response: Any) -> str | None:
    data = _provider_payload(response)
    if not isinstance(data, dict):
        return None
    value = data.get("requestId")
    return str(value) if value is not None else None


class VoiceCallService:
    """Dispatch one outbound call through OmniDimension's server SDK."""

    def __init__(self, *, ledger: DispatchLedger, provider_factory, agent_id: int | None):
        self._ledger = ledger
        self._provider_factory = provider_factory
        self._agent_id = agent_id

    def _result(
        self,
        *,
        status: DispatchStatus,
        lead_id: str,
        phone: str | None,
        dispatched: bool = False,
        request_id: str | None = None,
        reason: str | None = None,
    ) -> DispatchResult:
        return DispatchResult(
            status=status,
            dispatched=dispatched,
            lead_id=lead_id,
            normalized_phone_number=phone,
            agent_id=self._agent_id,
            reason_codes=[reason] if reason else [],
            provider_request_id=request_id,
        )

    def run(self, lead_id: str, phone_number: str, idempotency_key: UUID) -> DispatchResult:
        if not isinstance(self._agent_id, int) or isinstance(self._agent_id, bool) or self._agent_id <= 0:
            return self._result(
                status=DispatchStatus.blocked, lead_id=lead_id, phone=None,
                reason="outbound_agent_not_configured",
            )

        try:
            phone = normalize_indian_mobile(phone_number)
        except (TypeError, ValueError):
            return self._result(
                status=DispatchStatus.blocked, lead_id=lead_id, phone=None,
                reason="phone_invalid",
            )

        previous = self._ledger.lookup(idempotency_key)
        if previous:
            if previous[0] != lead_id or previous[1] != phone:
                return self._result(
                    status=DispatchStatus.duplicate, lead_id=lead_id, phone=phone,
                    reason="idempotency_key_reused_for_different_call",
                )
            return self._result(
                status=DispatchStatus.duplicate, lead_id=lead_id, phone=phone,
                reason=("previous_dispatch_outcome_uncertain"
                        if previous[2] == DispatchStatus.uncertain.value
                        else "duplicate_dispatch_key"),
            )

        try:
            provider: DispatchProvider = self._provider_factory()
        except Exception:
            return self._result(
                status=DispatchStatus.blocked, lead_id=lead_id, phone=phone,
                reason="provider_credentials_unavailable",
            )

        if not self._ledger.claim(idempotency_key, lead_id, phone):
            return self._result(
                status=DispatchStatus.duplicate, lead_id=lead_id, phone=phone,
                reason="duplicate_dispatch_key",
            )

        try:
            response = provider.dispatch_call(agent_id=self._agent_id, to_number=phone)
        except APIError as exc:
            uncertain = getattr(exc, "status_code", None) == 0
            result_status = DispatchStatus.uncertain if uncertain else DispatchStatus.provider_error
            self._ledger.finish(idempotency_key, result_status)
            return self._result(
                status=result_status, lead_id=lead_id, phone=phone,
                reason=("provider_outcome_uncertain" if uncertain
                        else "provider_rejected_dispatch"),
            )
        except Exception:
            self._ledger.finish(idempotency_key, DispatchStatus.uncertain)
            return self._result(
                status=DispatchStatus.uncertain, lead_id=lead_id, phone=phone,
                reason="provider_outcome_uncertain",
            )

        data = _provider_payload(response)
        if isinstance(data, dict) and data.get("success") is True and data.get("status") == "dispatched":
            request_id = _request_id(response)
            self._ledger.finish(idempotency_key, DispatchStatus.dispatched, request_id)
            return self._result(
                status=DispatchStatus.dispatched, lead_id=lead_id, phone=phone,
                dispatched=True, request_id=request_id,
            )

        # Do not retry an ambiguous provider response; it may have queued the call.
        self._ledger.finish(idempotency_key, DispatchStatus.uncertain)
        return self._result(
            status=DispatchStatus.uncertain, lead_id=lead_id, phone=phone,
            reason="provider_outcome_uncertain",
        )


CallDispatchService = VoiceCallService


def dispatch_voice_call(request: VoiceCallRequest) -> DispatchResult:
    settings = get_settings()
    service = VoiceCallService(
        ledger=DispatchLedger(settings.eligibility_db_path),
        provider_factory=lambda: OmniDimensionDispatchProvider(settings.omnidim_api_key),
        agent_id=settings.omnidim_outbound_agent_id,
    )
    return service.run(request.lead_id, request.phone_number, request.idempotency_key)
