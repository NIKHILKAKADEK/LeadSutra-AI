"""Eligibility-gated OmniDimension outbound dispatch with backend idempotency."""
from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from omnidimension import APIError

from app.schemas.outreach import (
    DispatchResult, DispatchStatus, VoiceCallContext,
)
from app.models.leads import LeadFileError, PreparedLead, normalize_indian_mobile
from app.services.calling_eligibility import CallingEligibilityStore, evaluate_eligibility
from app.services.leads import LeadJsonService
from app.integrations.omnidimension import OmniDimensionDispatchProvider
from app.services.outreach_repository import DispatchLedger
from app.core.config import get_settings
from app.schemas.outreach import VoiceCallRequest
from app.agents.voice.agent import outbound_agent_config
from app.services.proposals import ProposalFileError, ProposalJsonService


class DispatchProvider(Protocol):
    def get_agent(self, agent_id: int) -> Any: ...
    def dispatch_call(self, agent_id: int, to_number: str, call_context: dict[str, Any]) -> Any: ...


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


class VoiceCallService:
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
        proposal_service: ProposalJsonService | None = None,
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
        self._proposal_service = proposal_service
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

    def build_voice_context(self, lead: PreparedLead) -> VoiceCallContext:
        """Build fresh trusted context after run() passes pre-call eligibility.

        Optional proposal facts come only from a validated server-side artifact.
        Caller identity, contact permission and lead facts retain their sources.
        """
        if not self._represented_business_identity_verified:
            raise ValueError("represented business identity is not verified")
        name = self._represented_business_name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("represented business identity is not configured")
        proposal = self._proposal_service.load(lead.lead_id) if self._proposal_service else None
        proposal_fields = proposal.model_dump(exclude={"lead_id"}, exclude_none=True) if proposal else {}
        return VoiceCallContext(
            lead_business_name=lead.business_name,
            business_category=lead.category,
            business_location=lead.address,
            verified_business_name=name,
            contact_basis_status="verified",
            **proposal_fields,
        )

    def _call_context(self, lead: PreparedLead) -> dict[str, str]:
        """Serialize only declared fields from the current lead's validated model."""
        context = self.build_voice_context(lead)
        declared_variables = set(self._agent_config.get("dynamic_variables", {}))
        return context.to_provider_context(declared_variables)

    def _eligibility(self, lead_id: str, phone: str):
        return evaluate_eligibility(
            lead_id=lead_id,
            phone_number=phone,
            leads=self._lead_service.load(),
            store=self._eligibility_store,
            purpose=self._purpose,
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

        try:
            call_context = self._call_context(lead)
        except ProposalFileError:
            return self._blocked(lead_id, "proposal_unavailable", phone)

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

        # Refresh consent and lead eligibility
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


# Backward-compatible class name; no second implementation.
CallDispatchService = VoiceCallService


def dispatch_voice_call(request: VoiceCallRequest) -> DispatchResult:
    """Compose the existing workflow outside HTTP handlers."""
    settings = get_settings()
    service = VoiceCallService(
        lead_service=LeadJsonService(settings.lead_json_path),
        eligibility_store=CallingEligibilityStore(settings.eligibility_db_path),
        ledger=DispatchLedger(settings.eligibility_db_path),
        provider_factory=lambda: OmniDimensionDispatchProvider(settings.omnidim_api_key),
        agent_id=settings.omnidim_outbound_agent_id,
        enabled=settings.outbound_calls_enabled,
        purpose=settings.outbound_call_purpose,
        represented_business_name=settings.outbound_represented_business_name,
        represented_business_identity_verified=settings.outbound_represented_business_identity_verified,
        proposal_service=ProposalJsonService(settings.proposal_root),
    )
    return service.run(request.lead_id, request.phone_number, request.idempotency_key)
