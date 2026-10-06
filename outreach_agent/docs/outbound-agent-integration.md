# Outbound Agent and Dispatch Integration

This document describes the backend's local outbound configuration and guarded dispatch integration. It does not certify the live OmniDimension dashboard configuration for agent `261506` and does not enable or perform calls.

## Configuration flow

1. `app/services/voice_agent_configs.py::outbound_agent_config()` is the single source for the local outbound template: English (India), Hindi and Marathi; `Asia/Kolkata`; dynamic welcome/interruption configuration; static safety/conversation instructions; and declared dynamic-variable names.
2. `app/services/call_dispatch.py::CallDispatchService` loads that template. The provider language check uses its configured languages, and the validated context model filters values against the template's declared `dynamic_variables`. The template is not copied into a second language/variable allowlist.
3. `POST /api/v1/calls/dispatch` in `app/api/v1/calls.py` constructs the service from server-side `Settings`. The request schema accepts only lead ID, phone, and an idempotency UUID. It cannot choose an agent ID or context.
4. The dispatch service validates the lead and phone, then evaluates the existing calling eligibility rules. If dispatch is disabled, it returns `dry_run` before provider construction. If enabled, it additionally requires a configured represented-business name with its explicit verification setting true, fetches the configured agent and checks its ID, outbound call type, and supported languages, claims the idempotency key, repeats eligibility checks, then invokes the existing SDK `call.dispatch_call(agent_id, to_number, call_context=...)` adapter.

The SDK method's existing documented/installed shape is `agent_id`, `to_number`, and a dictionary `call_context`. The integration does not add a prompt field, agent-update field, webhook directive, or other provider request field. The local SDK implementation turns those arguments into the dispatch request body. The call-context dictionary values below are local template variable names; the backend does not claim that this proves agent `261506` is currently configured to use them.

## Required settings

| Setting | Default | Purpose |
|---|---|---|
| `OMNIDIM_OUTBOUND_AGENT_ID` | `261506` | Existing server-selected outbound agent ID. It is not accepted from API callers. |
| `OUTBOUND_CALLS_ENABLED` | `false` | Must remain false unless a separately authorized live-call enablement decision is made. |
| `OUTBOUND_CALL_PURPOSE` | `commercial_sales_call` | Server-selected purpose used by eligibility checks. |
| `OUTBOUND_REPRESENTED_BUSINESS_NAME` | unset | Name the agent represents; set only to an explicitly verified business identity. |
| `OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED` | `false` | Deployment attestation that the name has been verified. Enabled dispatch blocks unless this is true and the name is nonblank. The app cannot independently prove the attestation. |

`OMNIDIM_API_KEY` remains server-side and is not part of frontend or call context. Do not put credentials in logs or responses. `.env.example` includes the non-secret configuration keys; no live credentials or business identity are supplied by this change.

## Validated call context

`app/models/call_dispatch.py` defines three separate structures:

- `LeadCallContext`: lead business name and an optional verified lead/contact name. The current `SourceLead` schema does not expose a contact person name, so the optional name is omitted.
- `RepresentedBusinessContext`: a required nonblank represented-business name. The dispatcher constructs this only after server settings assert that the name is configured and verified.
- `OutboundCallContext`: these two data groups plus `contact_basis_status="verified"`, which is set only after the full backend eligibility evaluation succeeds.

`to_provider_context()` flattens those structures into only declared outbound-template variables. With the current lead source and configured identity, the context is:

```json
{
  "lead_business_name": "<validated lead business name>",
  "verified_business_name": "<server-configured verified represented business>",
  "contact_basis_status": "verified"
}
```

`lead_business_name` is omitted when the lead has no nonblank business name. `verified_lead_name`, offering, product facts, pricing, and human-transfer number are omitted because there is no verified configured/source value for them. The destination phone is passed separately as normalized `to_number`; email, score, private notes, full address, website, and arbitrary user data are not sent. Static agent instructions remain in `outbound_agent_config()` and are not mixed into per-lead data.

## Conversation instruction coverage

The local outbound template directs the agent to identify itself truthfully as an AI assistant; use English (India), Hindi, or Marathi and switch naturally; identify the represented business only when `verified_business_name` is present; use the target's `lead_business_name` without confusing it with the represented business; avoid unsupported claims; handle rejection politely; respect opt-out requests; avoid pressure or misleading statements; and not imply a human callback unless a callback process exists.

The template is a local configuration payload. Dispatch only sends per-call `call_context`; it does not create/update an agent or deliver `welcome_message`/`context_breakdown` through an undocumented dispatch field. Applying or reconciling those static instructions to the existing live agent requires a separately verified provider configuration workflow. This implementation makes no provider-side change.

## Safety behavior preserved

- Missing, unknown, denied, revoked, expired, incomplete, or wrong-purpose consent blocks dispatch.
- Unknown/suppressed suppression state, missing/unapproved telecom checks, stale calling-hours checks, and missing/exhausted attempt limits block dispatch.
- Phone normalization and lead-phone association are checked before eligibility. Eligibility is checked twice on enabled dispatch, including immediately before the provider call.
- A missing or unverified represented-business identity blocks enabled dispatch before provider construction.
- Idempotency ledger behavior, configured-agent ID/type validation, and sanitized provider errors remain in place.
- Disabled mode returns a dry-run result without constructing the provider, verified by `tests/test_call_dispatch.py::test_disabled_dispatch_is_dry_run_and_never_contacts_provider`.
- No code path in the tests makes a real provider call; dispatch tests use mocks.

## Limitations and operational prerequisites

1. The live settings of OmniDimension agent `261506` have not been retrieved. Local language/timezone/welcome/prompt values are not proof of dashboard state.
2. The new verification boolean is an administrative configuration assertion, not a verification service or evidence store. Set it true only after an authorized business owner validates the represented identity.
3. No verified offering, approved product facts, pricing, human transfer route, or verified person name is available. These values are intentionally not fabricated or sent.
4. The backend instruction template is not automatically applied to the live agent. Use an authorized and documented provider agent-configuration workflow to reconcile it before any future live-call decision.
5. The eligibility service can block dispatch but does not make the live conversation itself a legal determination. Telecom preference/route checks remain externally attested; the app does not query DND.
6. Opt-out language is present in the local prompt template, but persistent capture of a call-time opt-out still depends on a separately implemented, authenticated call-result integration. Do not claim the prompt alone updates suppression.
7. No frontend work or provider call is part of this integration. `OUTBOUND_CALLS_ENABLED` remains false.

## Verification

Relevant tests are `tests/test_voice_agent_configs.py`, `tests/test_call_dispatch.py`, `tests/test_calling_eligibility.py`, and `tests/test_lead_management_api.py`. They cover local template properties, server-selected agent behavior, context filtering, identity gating, fail-closed eligibility, mocked dispatch, and dry-run behavior. Their execution result for this change is recorded in the implementation report; test code never uses a live OmniDimension client for dispatch.
