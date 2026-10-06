# Test Business Identity Configuration Guide

This guide documents the represented-business settings found in `app/core/config.py`, `.env.example`, `README.md`, and the outbound dispatch implementation. No configuration or application files were changed to create this guide. Do not enable provider dispatch for a fictional test identity.

## Environment variable names

| Purpose | Exact setting | Code default | Meaning |
|---|---|---|---|
| Represented business name | `OUTBOUND_REPRESENTED_BUSINESS_NAME` | unset (`None`) | Server-side business identity the outbound assistant may represent. |
| Identity verification flag | `OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED` | `false` | Operator attestation that the configured identity was verified. The application does not independently verify the truth of this flag. |
| Outbound agent ID | `OMNIDIM_OUTBOUND_AGENT_ID` | `261506` | Server-selected OmniDimension agent. It is not accepted from dispatch request input. |
| Outbound dispatch enablement | `OUTBOUND_CALLS_ENABLED` | `false` | Enables/disables the provider dispatch path. Keep false for local tests. |

These names are present in `.env.example`; `README.md` describes the identity requirements. `app/core/config.py::Settings` maps them to Pydantic settings and reads `.env` plus process environment variables (case-insensitive). The complete outbound flow is wired in `app/api/v1/calls.py::dispatch_outbound_call()` and `app/services/call_dispatch.py::CallDispatchService`.

## How business identity enters `call_context`

The name is loaded from the server-side setting and passed by the route to `CallDispatchService`. It is never taken from the request body. When enabled dispatch has passed lead and eligibility checks, the service requires both a nonblank name and a true verification flag. `_call_context()` validates the value through `RepresentedBusinessContext`, then `OutboundCallContext.to_provider_context()` maps it to the exact key `verified_business_name`. The adapter passes that mapping using the SDK `call_context` argument.

The request schema forbids extra fields. An API caller cannot override the agent ID, represented-business name, or call context. When dispatch is disabled, the service returns `dry_run` before it constructs the provider or builds the call context; changing the local name does not turn a dry run into a context-substitution test.

## Missing or unverified identity behavior

- On the enabled path, missing, whitespace-only, or unverified identity returns a blocked result with reason `represented_business_identity_unverified`, before provider construction.
- A true verification flag with no nonblank name still blocks.
- The flag is an administrative assertion, not proof supplied by the application. Set it true only after an authorized owner/operator has verified the actual represented business.
- `OUTBOUND_CALLS_ENABLED=false` prevents provider dispatch regardless of the identity settings.

## Safe local setup

For a local dry-run configuration, use a clearly fictional label and leave its verification flag false. Example `.env` values (these are examples only; they are not configured by this guide):

```dotenv
OMNIDIM_OUTBOUND_AGENT_ID=261506
OUTBOUND_CALLS_ENABLED=false
OUTBOUND_REPRESENTED_BUSINESS_NAME=Example Test Business (Fictional)
OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED=false
```

You can instead set these values in a PowerShell process for a local run without editing `.env`:

```powershell
$env:OMNIDIM_OUTBOUND_AGENT_ID = '261506'
$env:OUTBOUND_CALLS_ENABLED = 'false'
$env:OUTBOUND_REPRESENTED_BUSINESS_NAME = 'Example Test Business (Fictional)'
$env:OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED = 'false'
```

The fictional name and false flag are safe for dry-run configuration inspection, but cannot pass the enabled identity gate. Do not change the enablement flag. For context-construction coverage, use isolated tests with a mocked provider and synthetic fixtures; never send this fictional identity to OmniDimension. The existing focused tests include:

- `tests/test_call_dispatch.py::test_eligible_lead_dispatches_and_sends_minimal_context`
- `tests/test_call_dispatch.py::test_missing_or_unverified_represented_business_blocks_enabled_dispatch`
- `tests/test_call_dispatch.py::test_disabled_dispatch_is_dry_run_and_never_contacts_provider`

Those dispatch-path tests inject synthetic service settings and a mock provider; they do not require a fictional identity to be marked as a real verified business in `.env`.

## Validation procedure

1. Confirm `OUTBOUND_CALLS_ENABLED=false` in the process and local configuration. Do not print unrelated environment variables or `.env` contents; they may contain credentials.
2. Check only the four nonsecret setting names and expected local values. Do not display `OMNIDIM_API_KEY`, bearer tokens, or provider headers.
3. Run the three focused tests above from the project virtual environment. They verify minimal context mapping, missing/unverified identity blocking, and that disabled mode does not construct or contact the provider.
4. Do not use the protected dispatch route to test context construction: with dispatch disabled it returns before context construction. Use the mocked tests for that assertion.
5. Do not interpret a configured name or verification boolean as telecom consent, caller permission, suppression clearance, or a legal determination. Eligibility checks remain required.

## Restart behavior

Yes. Restart the FastAPI application after changing `.env` or process-level configuration. `get_settings()` is cached with `lru_cache`, and the app reads settings during import; a running process should not be expected to reload changed `.env` values. A new process also ensures shell-scoped environment changes are applied predictably.

## Cleanup

- For process-scoped PowerShell variables, remove them when finished:

  ```powershell
  Remove-Item Env:OMNIDIM_OUTBOUND_AGENT_ID -ErrorAction SilentlyContinue
  Remove-Item Env:OUTBOUND_CALLS_ENABLED -ErrorAction SilentlyContinue
  Remove-Item Env:OUTBOUND_REPRESENTED_BUSINESS_NAME -ErrorAction SilentlyContinue
  Remove-Item Env:OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED -ErrorAction SilentlyContinue
  ```

- If an operator separately created or edited a local `.env`, restore its prior contents or remove only the test entries after stopping the app. This task did not edit `.env`.
- Restart the app after cleanup. Keep dispatch disabled.
- Do not set the fictional identity's verification flag to true in any process that can reach a real provider. For mocked tests, use isolated test fixtures and mocks as the existing tests do.

## Limitations and risks

- The identity verification boolean is only an operator assertion; there is no application-side identity evidence service.
- The outbound agent ID default is `261506`, but local configuration does not itself prove current remote settings.
- A fictional identity must never be used for a real call. A name and true flag are not sufficient to satisfy consent, suppression, telecom, calling-hours, attempt-limit, or other eligibility requirements.
- Changing the business name requires an application restart to load consistently, but changing it does not verify that the provider substitutes `{{verified_business_name}}` at runtime.
- This guide does not authorize dispatch, change the current enablement setting, or make provider requests.
