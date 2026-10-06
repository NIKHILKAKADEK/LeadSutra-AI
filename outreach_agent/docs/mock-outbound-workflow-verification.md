# Mock-Only Outbound Workflow Verification

Project: LeadSutra AI backend  
Agent configured by default: `261506`  
Scope: static workflow/test inspection and existing mock-test review only. No source or test files were changed.

## Summary

The existing dispatch service and tests cover the principal safety gates and the provider boundary using an injected mock. The fully eligible synthetic fixture expects this minimal context:

```json
{
  "lead_business_name": "Fixture Business",
  "verified_business_name": "Verified Caller Ltd.",
  "contact_basis_status": "verified"
}
```

The test asserts that payload at the mocked provider call. It does not establish behavior against the real OmniDimension service. The complete test suite could not be executed because Python is unavailable in the shell and the virtual environment points to a missing Python 3.12 executable. Therefore none of the existing test assertions can be reported as runtime-passing in this verification.

This is **not** a production-readiness finding. No provider call was made, and live dispatch, telecom authorization, timezone behavior, variable substitution, and provider-side delivery remain outside this mocked verification.

## Workflow trace

```mermaid
sequenceDiagram
    participant API as Protected POST /api/v1/calls/dispatch
    participant L as LeadJsonService / SourceLead
    participant E as CallingEligibilityStore + evaluator
    participant C as Context and business-identity gate
    participant I as DispatchLedger
    participant A as Provider agent GET adapter
    participant P as Provider dispatch boundary

    API->>API: Validate request (lead_id, phone_number, idempotency UUID)
    API->>L: Load lead JSON and validate records
    L-->>API: Prepared leads with normalized phone entries
    API->>API: Find lead ID and require submitted phone associated with that lead
    API->>E: Check qualification, consent/purpose/evidence, expiry/revocation,
    API->>E: suppression, telecom preference/route, calling hours, attempt limits
    E-->>API: Eligibility result and reason codes
    alt Blocked or dispatch disabled
        API-->>API: Return blocked or dry_run; dry_run exits before provider factory
    else Dispatch enabled and eligible
        API->>C: Require verified represented-business identity; build allowlisted context
        API->>I: Check idempotency key
        API->>A: Construct injected provider and retrieve configured agent
        A-->>API: Require expected ID, outgoing type, supported languages
        API->>I: Atomically claim idempotency key
        API->>E: Recheck eligibility immediately before provider boundary
        alt Second check blocked
            API->>I: Finish ledger as blocked
            API-->>API: Return blocked; do not dispatch
        else Second check passes
            API->>P: dispatch_call(agent_id, normalized_phone, minimal_context)
            P-->>API: Record dispatched, provider_error, or uncertain; do not retry
        end
    end
```

### Implementation details

1. `app/api/v1/calls.py::dispatch_outbound_call()` is admin-protected. It constructs `LeadJsonService`, the eligibility store and ledger from server settings, and injects the provider factory. The API request schema forbids extra fields; callers cannot supply an agent ID or call context.
2. `app/services/leads.py::LeadJsonService.load()` reads only the configured JSON path, validates every record with `SourceLead`, then prepares leads. `app/models/leads.py::prepare_lead()` normalizes supported Indian mobile numbers and retains the association between the lead and its normalized numbers.
3. `CallDispatchService._prepare()` checks the configured agent ID, normalizes the requested phone, finds the requested lead, requires the phone to be associated with that lead, and requires a configured purpose.
4. `CallDispatchService._eligibility()` invokes `evaluate_eligibility()` with SQLite consent, suppression, telecom and operational checks. The evaluator requires a qualified lead, verified purpose-matched consent with evidence, valid expiry/revocation state, known not-suppressed state, fresh approved telecom preference and route, approved calling hours, and available attempt budget.
5. If eligibility passes but `enabled` is false, `run()` returns `dry_run` before represented-business validation, provider construction, agent retrieval, ledger claim, or dispatch. `app/core/config.py` defaults `outbound_calls_enabled` to false, and `.env` does not override it in this workspace.
6. In enabled mode, the service requires an explicitly verified, nonblank represented-business name. `_call_context()` uses the validated lead business name plus that configured represented-business name and `contact_basis_status="verified"`; `to_provider_context()` filters to the declared template variables. The destination phone is passed separately. Optional lead fields such as email, website, address, and scores are not in the context.
7. The service checks the idempotency ledger, obtains the remote agent through the injected provider, and validates its ID, outgoing call type, and configured languages. It claims the key, runs eligibility a second time, then reaches `dispatch_call()` only when the second check passes.
8. Provider API errors are sanitized. Nonzero API status becomes `provider_error`; transport status 0, general exceptions, and malformed/ambiguous response bodies become `uncertain`. The ledger keeps that terminal result so reusing the key returns duplicate/uncertain status rather than sending an automatic retry.

## Existing mock coverage reviewed

Test source: `tests/test_call_dispatch.py`, `tests/test_calling_eligibility.py`, and `tests/test_lead_management_api.py`.

`tests/test_call_dispatch.py` defines a synthetic `FixtureLeads` source, a `tmp_path` SQLite eligibility/ledger store, a `Mock` provider and a mocked factory. Its assertions cover:

- Eligible fixture dispatch returns the expected request ID and minimal `call_context` with lead business name, verified represented-business name, and `contact_basis_status="verified"`.
- Unknown consent blocks before provider construction/call.
- Revoked consent blocks.
- Suppressed phone blocks.
- Unknown telecom checks block.
- Invalid phone blocks before provider construction.
- Incoming/wrong-call-type agent and missing approved languages block before dispatch.
- Missing or unverified represented-business identity blocks before provider construction.
- Missing optional lead fields stay absent from context.
- Extra client-supplied agent ID/context is rejected by the request model.
- Duplicate idempotency key dispatches once.
- Provider 503 error is sanitized and not retried.
- Transport/API status 0 is recorded as uncertain and not retried.
- Dry-run reports eligible without constructing the provider factory or calling provider methods.
- Dispatch is disabled by default according to the `Settings` model field.

`tests/test_calling_eligibility.py` separately covers denied/unknown/pending consent, valid verified consent, expiry, missing evidence/wrong purpose, unknown suppression, suppression overriding consent, invalid phone, unapproved telecom/operational checks, and a fully eligible fixture. `tests/test_lead_management_api.py` includes protected-route, lead-specific eligibility, dry-run endpoint and phone-association checks.

These are tests present in source. Since pytest could not start, they are reviewed coverage, not executed results.

## Test execution results

- `python -m pytest -v` — **not run**; PowerShell could not find `python`.
- `.venv\Scripts\python.exe -m pytest -v` — **not run**; the virtual environment reports its configured Python executable is missing at `C:\Users\kakde\AppData\Local\Programs\Python\Python312\python.exe`.

No test result count is claimed.

## Missing integration tests to propose before any source change

No tests or source were modified. The following are worthwhile additions before relying on the workflow:

1. **Enabled API route end-to-end with a mock factory:** issue an authenticated request to `/api/v1/calls/dispatch` with enabled test settings and a temporary lead file/database; assert the route wires the configured agent/business identity correctly, passes only the expected provider arguments, and never creates the real OmniDimension client.
2. **Eligibility changes after agent verification:** configure the mock `get_agent()` to revoke consent or add suppression before returning; assert the second eligibility check blocks, marks the ledger blocked, and never calls `dispatch_call()`.
3. **Generic transport exception and malformed response retry protection:** test a non-`APIError` exception and ambiguous/malformed response, then reuse the same idempotency key and assert no second provider dispatch occurs.
4. **Idempotency key reused for another lead/phone:** assert the request is rejected as duplicate with `idempotency_key_reused_for_different_call` and does not dispatch.
5. **Concurrent idempotency claim:** race two service runs with the same key using a thread-safe fixture/provider mock; assert at most one dispatch attempt. The current tests cover sequential duplicate use, not concurrency.
6. **Specific telecom denial and stale operational checks through dispatch:** current tests cover unknown telecom in the dispatch service and denied/unapproved eligibility at the evaluator level; an enabled-path dispatch test should assert explicit denied preference, denied route, stale hours and exhausted attempts each prevent the provider boundary.
7. **Missing or malformed lead source at dispatch boundary:** assert source parsing failure blocks before provider construction and does not claim an idempotency key.

These proposals are test-only recommendations. No test/code modification was made because this task asked for verification and documentation.

## Remaining limitations

- Mock tests cannot verify network transport, OmniDimension authentication, actual API request serialization, provider acceptance, call delivery, audio, or runtime variable resolution.
- The provider dispatch success test uses a synthetic response and does not prove that a real provider response is identical or that an accepted request means a completed/answered call.
- Consent, telecom preference/route and calling-hours records are test fixtures. This audit did not inspect or change production records, and it does not independently establish legal consent or an authorized telecom-route check.
- A successful mock dispatch assertion does not make the workflow production-ready. The current default remains dispatch disabled.
- The full test suite remains unexecuted in this environment due to the missing Python interpreter.

## Safety record

No real OmniDimension dispatch request or phone call was made. No provider settings were changed. No scraper or `leads.json` file was modified. No production consent or eligibility records were changed. No frontend work was done. `OUTBOUND_CALLS_ENABLED` remains false. No source or test file was modified.
