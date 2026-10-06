# Outbound Voice Pre-Test Readiness Audit

Audit date: 2026-10-05  
Scope: read-only backend and existing remote-agent evidence review. No calls, dispatches, provider writes, or production data changes were made.

## Overall readiness: NOT READY

The local dispatch path has fail-closed safeguards and an established mock-test suite. A controlled voice test is not ready: the backend cannot currently be started in this environment because the virtualenv launcher points to a missing Python interpreter; no trusted represented-business identity is configured in application defaults; required telecom/compliance attestations are external inputs rather than checks performed by this application; and actual language/audio behavior and runtime dynamic-variable substitution have not been tested. `OUTBOUND_CALLS_ENABLED` remains false.

## Verified items

### Backend and health route

- `app/main.py` constructs the FastAPI app, registers the versioned router, and defines `GET /health`, returning status, application, environment, and API version.
- `tests/test_health.py` contains import/startup, health-response, and router-registration tests.
- Runtime verification was attempted: `.venv\\Scripts\\python.exe --version` and `.venv\\Scripts\\python.exe -m pytest tests/test_health.py -q` both failed with `No Python at ...Python312\\python.exe`. No process was listening on port 8000. Therefore the app startup and health endpoint are **not runtime-verified in this audit**.

### OmniDimension connectivity and remote agent evidence

- `app/services/omnidimension.py::OmniDimensionService.verify_connection()` rejects a missing key, creates the SDK client, and calls `agent.list()`. This is a read/list connectivity operation and does not dispatch a call. Exceptions are replaced with a sanitized connection error.
- `tests/test_omnidimension.py` tests the connection route using a mocked SDK, including that it returns no agent data and sanitizes credential/provider errors. Those tests were not run in this environment.
- The previously recorded documented read-only GET evidence in `docs/outbound-agent-final-verification.md` reports Agent `261506`, name `LeadSutra AI - Outbound Sales Agent`, type `Outgoing`; English (India), Hindi, and Marathi; Cartesia/Riya; Soniox with `en hi mr`; `gpt-4.1-mini`; dynamic welcome and welcome interruption enabled; and the exact welcome placeholder `{{verified_business_name}}`. The report records ten enabled remote conversation sections.
- That prior GET reported agent `timezone` as boolean `false`. The documented response semantics do not establish an IANA timezone from that value, so timezone remains **unverified**. This audit did not issue another provider request.
- Remote welcome text and settings above are evidence recorded in the existing verification document, not proof of live conversation behavior.

### Dispatch, context, identity, and dry-run controls

- `app/core/config.py::Settings` defaults `omnidim_outbound_agent_id` to `261506`, `outbound_calls_enabled` to `False`, represented-business name to `None`, and its verification flag to `False`. The request model in `app/models/call_dispatch.py::DispatchRequest` accepts lead ID, phone number, and idempotency key, not an agent ID or arbitrary provider context.
- `app/api/v1/calls.py::dispatch_outbound_call()` constructs the service from server settings. `app/services/call_dispatch.py::CallDispatchService.run()` validates the lead and associated normalized phone and evaluates eligibility. When disabled, it returns the dry-run result before constructing the provider. On the enabled path it blocks a missing, blank, or unverified represented-business identity before provider construction. It uses the configured agent ID and validates the remote agent before the final eligibility recheck and dispatch boundary.
- `app/services/call_dispatch.py::_call_context()` and `app/models/call_dispatch.py::OutboundCallContext.to_provider_context()` map the trusted configured represented-business value to the exact key `verified_business_name`, alongside only available validated lead context and eligibility marker. The provider adapter passes the context under the SDK's `call_context` argument. The remote welcome's exact `{{verified_business_name}}` spelling matches this key.
- Current settings defaults provide no represented-business value and leave its verification flag false. A real enabled attempt using these defaults will fail closed with `represented_business_identity_unverified`. The actual remote substitution of the welcome placeholder is not proven by source/mock tests or the GET text.
- `OUTBOUND_CALLS_ENABLED` is false by source default and is also shown false in `.env.example`. The environment inspection found no outbound-setting override. The current effective value could not be loaded through `get_settings()` because Python is unavailable; source/default evidence says disabled, and no dispatch was attempted.

### Eligibility and opt-out controls

- `app/services/calling_eligibility.py::evaluate_eligibility()` requires a valid normalized phone associated with an existing qualified lead; verified, evidenced, nonexpired, nonrevoked, purpose-matched consent; known `not_suppressed` status; fresh approved telecom preference and route statuses; approved calling hours; and an available attempt budget. Missing, unknown, stale, or unsuccessful checks block eligibility.
- `app/api/v1/calling_eligibility.py` exposes consent and suppression management under admin authorization. Suppression is persisted separately in SQLite and overrides consent at evaluation time. Unknown suppression blocks.
- `app/services/voice_agent_configs.py::_OUTBOUND` includes refusal and opt-out instructions. The prompt text alone does not persist an in-call opt-out. Existing integration documentation (`docs/outbound-agent-integration.md`) says persistent capture depends on a call-result/webhook integration and is not available as an implemented confirmed path here.

## Unverified items and blockers

1. **Application runtime:** Python 3.12 referenced by the virtualenv is missing; no live `/health` request could be made.
2. **Represented business:** No trusted business name and verified attestation are available through the settings defaults inspected. Enabled dispatch correctly blocks until both are configured from an authoritative source.
3. **Telecom and legal compliance evidence:** The service stores/checks external attestations for consent/lawful basis, telecom preference, and approved route. No authorized telecom/DND provider integration is implemented here. The application must not be represented as verifying DND itself. Applicable sender/telemarketer registration, consent/preference scrubbing, route, and any required telecom-provider evidence must be confirmed through the authorized operational providers before a real test.
4. **Timezone:** Remote agent timezone is unresolved; `false` is not interpreted as `Asia/Kolkata`.
5. **Dynamic substitution:** Remote welcome contains the placeholder and backend context uses the matching key, but there is no proof that the provider substitutes the per-call value for this agent at runtime. Existing provider verification notes that the remote GET exposed `dynamic_variables` as an empty array.
6. **Conversation behavior:** No real or internal voice test has established audio quality, pronunciation, English/Hindi/Marathi switching, interruptions, greeting timing, refusal handling, or opt-out behavior.
7. **Opt-out persistence:** There is backend suppression storage, but no verified call-result integration that converts the recipient's live opt-out into a durable suppression record.
8. **Test execution:** Tests were inspected but not run because the virtualenv's Python executable cannot find its configured interpreter. No passed-test count is asserted.

## Existing test coverage inspected

- `tests/test_health.py`: app import/startup shape, `/health` response, and versioned-router registration.
- `tests/test_omnidimension.py`: mocked connection success, missing credentials, and sanitized SDK failure.
- `tests/test_voice_agent_configs.py`: local template languages, timezone declaration, dynamic greeting configuration, and outbound safety instructions.
- `tests/test_calling_eligibility.py`: consent status/evidence/scope/expiry, suppression, phone validity, telecom/operational checks, and fully eligible fixture.
- `tests/test_call_dispatch.py`: minimal context, consent/revocation/suppression/telecom/phone blocks, agent validation, provider error/uncertainty handling, idempotency, dry-run, business identity gate, caller override rejection, eligibility recheck, and concurrency.
- `tests/test_lead_management_api.py`: authenticated mocked dispatch route, request validation, lead-phone association, eligibility/context wiring, and dry-run behavior.

These names describe existing test coverage only; none were executed successfully in this audit.

## Exact steps before a controlled internal voice test

1. Restore/install the Python version expected by `.venv` or recreate the virtual environment; run `python -m pytest -v` and resolve failures.
2. Start the app in a safe nonproduction environment and verify `GET /health` returns HTTP 200. Verify the OmniDimension connection endpoint with its server-side credential; it only lists agents and must not dispatch.
3. Obtain authorized business-owner evidence for the represented business identity, configure that exact name server-side, and set the identity verification attestation only after review. Do not derive this identity from scraped lead data.
4. Have the responsible compliance/telecom operator confirm applicable sender and telemarketer registration, authorized route, consent/preference scrubbing, and the specific valid evidence for this test population. Populate only real, fresh, authorized checks. Do not treat stored status as an application-performed DND check.
5. Confirm suppression records and establish an operational process to capture an opt-out durably before any call; otherwise do not use the prompt as proof that suppression will be updated.
6. Resolve agent timezone with authoritative provider/dashboard evidence, and establish the provider's actual dynamic-variable substitution behavior through an authorized, tightly controlled internal test. This audit does not authorize that test.
7. Review the exact lead, destination, consent basis, route, calling hours, attempt limit, business identity, agent configuration, and idempotency for any later approved internal test. Keep dispatch disabled until a separate authorized decision; no change is made here.

## Change record

Only `docs/outbound-voice-pretest-readiness.md` was created. No application source, tests, database, `.env`, scraper, lead data, frontend, or provider settings were modified. No provider dispatch or phone call was made. `OUTBOUND_CALLS_ENABLED` was not changed.

