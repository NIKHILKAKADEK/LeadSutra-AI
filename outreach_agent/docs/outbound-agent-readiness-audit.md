# Outbound Voice Agent Readiness Audit

Project: `D:\Leadsutra_AI\leadsutra_backend`  
Outbound agent ID from backend defaults/configuration: `261506`  
Audit date: 2026-10-05  
Scope: read-only source/configuration inspection and existing relevant test invocation attempts. No provider API calls were made.

## Readiness summary

**Not ready for live outbound calling.** The backend contains a gated dispatch path and reusable outbound prompt/configuration template, but the template is not connected to runtime dispatch or proven to be deployed to OmniDimension agent `261506`. The template's verified caller-business and lawful-basis variables are placeholders and are not populated by the dispatcher. In particular, `call_context.business_name` is the target lead's business name, while the prompt's `verified_business_name` is intended to identify the business represented by the caller. No authenticated provider response or supplied dashboard export was inspected, so actual agent settings cannot be confirmed.

The dispatch implementation is fail-closed on consent, suppression, compliance, operating-hours and attempt checks. The effective application setting remains disabled: `outbound_calls_enabled` defaults to `false`; there is no process environment override or `.env` entry for `OUTBOUND_CALLS_ENABLED`; `.env.example` sets it to `false`. No secret values were read or displayed. No actual call was attempted.

## Verified working components

### Backend agent configuration source

`app/services/voice_agent_configs.py` defines `SUPPORTED_LANGUAGES` as exactly:

- English (India)
- Hindi
- Marathi

It defines `AGENT_TIMEZONE = "Asia/Kolkata"`. `outbound_agent_config()` returns a configuration template with `call_type: "Outgoing"`, dynamic welcome enabled, welcome interruption enabled, and prompt sections covering opening, eligibility boundaries, qualification/factual accuracy, language and human escalation. The outbound template includes opt-out/refusal instructions and says not to invent lead/business facts.

`tests/test_voice_agent_configs.py` asserts these languages, timezone, dynamic welcome flags and selected safety language for the returned templates. These tests exercise Python configuration objects only; they do not establish deployed OmniDimension dashboard settings.

### Agent ID, dispatch and phone checks

- `app/core/config.py` defaults `omnidim_outbound_agent_id` to `261506`; `.env.example` also contains `OMNIDIM_OUTBOUND_AGENT_ID=261506`. The actual `.env` was queried only for this non-secret setting and had no override; the process environment had none. The effective configured value is therefore the code default, `261506`.
- `DispatchRequest` in `app/models/call_dispatch.py` accepts only `lead_id`, `phone_number`, and `idempotency_key` (UUID); `extra="forbid"` rejects a caller-supplied `agent_id`, `call_context`, purpose or provider field.
- `CallDispatchService._prepare()` in `app/services/call_dispatch.py` uses its constructor-supplied server-side agent ID, rejects missing/invalid IDs, normalizes the phone using `normalize_indian_mobile()`, loads the configured lead source, verifies the phone is associated with that lead, and rejects an empty server-configured purpose.
- When the enabled provider path is reached, `run()` fetches the configured agent and checks returned ID equals the configured ID, call type is `outgoing` or `outbound`, and provider-reported language labels include all supported languages. This is source-code behavior; this audit did not call the provider, so no live check occurred.
- `OmniDimensionDispatchProvider` in `app/services/call_dispatch.py` uses `OmniDimensionService.create_client()` and calls the SDK's `agent.get()` and `call.dispatch_call()` methods. `app/services/omnidimension.py` holds the API key server-side and sanitizes connection errors.

### Dispatch information sent to the provider

`CallDispatchService._call_context()` constructs context server-side. It sends `approved_languages` plus available non-empty lead fields as `business_name`, `website`, `category`, and `business_location`. It does not send the lead email, lead ID, lead score, qualification status, or raw phone in context. The normalized destination phone is separately sent as `to_number`. No arbitrary browser context is accepted by the request schema.

This is a bounded selection from the lead, but **strict minimum-necessary status is not established**: website, category, and full address are sent and their need is not justified by the active prompt/runtime mapping. The key `business_name` is from the *target lead*, not a separately verified caller/client business identity.

## Missing or unverified components

### Agent 261506 is not verified against the template

- `outbound_agent_config()` is referenced by its tests and exported as a reusable payload; it is not called by `app/services/call_dispatch.py`, agent creation/update logic, or app startup. The repository does not show that this template was applied to Agent 261506.
- The template name is `LeadSutra Outbound Assistant`. Earlier project-provided context described the existing agent as `LeadSutra AI – Outbound Sales Agent`; there is no source mapping that confirms either name is the live name for ID 261506. Treat this as an unverified naming/configuration mismatch, not a confirmed provider mismatch.
- The configured languages/timezone/dynamic greeting are verified only in the local template. Actual agent language list is checked only when dispatch is enabled and the request enters provider flow. Actual timezone, dynamic greeting flags, interruption settings and instructions are not retrieved by the current pre-dispatch validation.

### Caller and lead context are incomplete/misaligned

- The outbound template requires `verified_business_name`, `verified_offering`, `approved_product_facts`, and `approved_pricing`; it also defines `verified_lead_name`, `contact_basis_status`, and `human_transfer_number`. Their configured values are placeholder strings in `voice_agent_configs.py`.
- `_call_context()` does not populate those names. It supplies `business_name`, website, category, business location and approved languages. The target lead's name should not be substituted for the business the agent represents.
- The validated lead source model in `app/models/leads.py` contains business name, website, category, address, phone/email and contact phone/email collections; it does not define a lead/contact person name. Unknown fields are ignored. No contact name can be supplied from the current validated schema without extending verified source data.
- The dispatcher does not pass `contact_basis_status`. The template's instruction to avoid pitching unless this value is exactly `verified` therefore cannot be assumed to be effective in a deployed agent. Backend eligibility gates dispatch itself, but that does not verify what the live prompt receives during the conversation.
- Human transfer number and verified product/pricing facts are not sourced from backend settings or passed to dispatch. No transfer capability or factual sales content can be confirmed.

### Conversation instructions are only a local template

The template covers a greeting, identifying as an AI assistant, asking if the contact is available, supported languages, brief qualification, factual accuracy, refusal, opt-out and conditional human escalation. Gaps/unverified areas:

- No verified business identity/offering is available for the introduction.
- No actual deployed greeting or language-switching behavior was inspected.
- Enquiry/objection handling has only general instructions to ask concise questions and record objections; no approved response policy, product facts, pricing, or escalation playbook is configured in backend source.
- Opt-out instructions tell the agent to record suppression, but there is no implemented conversation-result/webhook path in this backend that can convert an in-call opt-out into a suppression record. Do not rely on prompt text alone to persist opt-outs.
- Human escalation is conditional on a verified transfer route, but the route remains an unconfigured placeholder and dispatch does not provide one.
- The transcriber provider in the template is `Soniox`; it is also not verified as a live setting on Agent 261506.

## Safety and compliance checks

`app/services/calling_eligibility.py` implements fail-closed checks. `evaluate_eligibility()` blocks if the lead is missing, the phone is not associated, the lead is not `Qualified`, consent is absent/unknown/incomplete/wrong-purpose/expired/revoked/denied/pending, suppression is absent/unknown/suppressed, telecom preference/route is not approved, calling hours are not approved/fresh, or attempts/limit are missing/stale/exhausted. Consent validation in `_reason_consent()` requires verified status and scope matching the server-configured purpose, source, evidence reference, verification timestamp and verifier. The eligibility response does not expose evidence references.

`CallDispatchService.run()` evaluates eligibility before dispatch, returns early in disabled mode, and—if live mode were enabled—re-evaluates eligibility immediately before the provider dispatch. `DispatchStatus.dry_run` is returned for eligible requests when dispatch is disabled. The early return occurs before provider construction, and `tests/test_call_dispatch.py::test_disabled_dispatch_is_dry_run_and_never_contacts_provider` asserts the provider factory and dispatch method are not called.

The consent/suppression/compliance persistence and management API is protected by admin role; eligibility preview and lead reads use reviewer role; dispatch requires admin role. The underlying reviewer/admin credentials are static backend bearer tokens configured via environment settings, not end-user authentication. The app records external telecom attestations; it does not itself perform a DND lookup or telecom route check. A valid consent record must not be treated as a substitute for applicable telecom requirements.

## Exact files and functions involved

| File | Relevant functions/classes | Audit finding |
|---|---|---|
| `app/services/voice_agent_configs.py` | `SUPPORTED_LANGUAGES`, `AGENT_TIMEZONE`, `_OUTBOUND`, `outbound_agent_config()` | Local reusable outbound template; not linked to agent 261506 at runtime; contains unresolved placeholders. |
| `app/core/config.py` | `Settings.omnidim_outbound_agent_id`, `Settings.outbound_calls_enabled` | Default ID 261506; outbound disabled by default. |
| `app/api/v1/calls.py` | `dispatch_outbound_call()` | Passes server settings and backend services to dispatch; does not accept an agent ID/context from client. |
| `app/models/call_dispatch.py` | `DispatchRequest`, `DispatchResult`, `DispatchStatus` | Request forbids arbitrary fields; request/result state schema. |
| `app/services/call_dispatch.py` | `OmniDimensionDispatchProvider`, `CallDispatchService._prepare()`, `_call_context()`, `_eligibility()`, `run()` | Provider adapter, ID/type/language verification, normalization, context, eligibility gates, disabled dry-run branch. |
| `app/services/omnidimension.py` | `OmniDimensionService.create_client()`, `verify_connection()` | Server-side API-key client creation and sanitized connectivity errors. |
| `app/models/leads.py` | `SourceLead`, `SourceBusiness`, `SourceContacts`, `prepare_lead()`, `normalize_indian_mobile()` | Actual validated lead fields, missing person name, phone validation/normalization. |
| `app/services/leads.py` | `LeadJsonService.load()` | Read-only lead JSON loading and validation. |
| `app/services/calling_eligibility.py` | `CallingEligibilityStore`, `_reason_consent()`, `evaluate_eligibility()` | Consent/suppression/compliance storage and fail-closed evaluator. |
| `app/api/v1/calling_eligibility.py` | `_principal()`, `require_admin()`, `require_reviewer()`, consent/suppression/telecom endpoints, `preview_eligibility()` | Static bearer-token role checks and protected management routes. |
| `tests/test_voice_agent_configs.py` | template tests | Verifies template constants/instructions, not provider dashboard state. |
| `tests/test_call_dispatch.py` | dispatch tests, especially disabled dry-run and blocked consent | Mocked provider checks; no actual calls. |
| `tests/test_calling_eligibility.py` | consent and eligibility tests | Proves fail-closed logic with fixtures. |
| `tests/test_lead_management_api.py` | protected dispatch API dry-run tests | Proves API dry-run does not construct the provider in the tested setup. |

## Test results

Attempted the relevant existing test set:

```text
python -m pytest tests/test_voice_agent_configs.py tests/test_call_dispatch.py tests/test_calling_eligibility.py tests/test_lead_management_api.py -v
```

Result: **not run**. PowerShell reports `python` is not recognized (exit code 1). The project virtual environment launcher was also attempted:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_voice_agent_configs.py tests/test_call_dispatch.py tests/test_calling_eligibility.py tests/test_lead_management_api.py -v
```

Result: **not run**. It reports no Python at `C:\Users\kakde\AppData\Local\Programs\Python\Python312\python.exe` (exit code 1). No test collection/results are claimed. Tests were not modified.

## Recommended next implementation step

Before any live dispatch, obtain an authenticated, read-only provider response or an authoritative Agent 261506 configuration export and reconcile it with the backend template. Then define a verified server-side caller-business identity, approved offering/facts/pricing, transfer policy/route, and lead-name source (or explicitly omit the name); map only those confirmed values to the provider's verified context contract. Resolve what the active deployment prompt expects for eligibility status and ensure opt-outs have a durable, authenticated suppression path. Keep `OUTBOUND_CALLS_ENABLED=false` until this reconciliation, compliance review, tests, and a separately authorized readiness decision are complete.

## Audit limitations and safety

No authenticated provider response/configuration export was available or requested during this read-only audit, so no dashboard properties are represented as live-verified. The lead JSON was not opened. The `.env` was queried only for the non-secret outbound-toggle and agent-ID settings; no secret values were displayed. No application files, production data, lead records, `.env` values, scraper files, or provider settings were changed. No actual outbound call or OmniDimension API request was made.
