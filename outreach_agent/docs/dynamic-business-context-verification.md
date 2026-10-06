# Dynamic Business Context Verification — Agent 261506

Verification date: 2026-10-05  
Scope: read-only backend/configuration review and documented provider behavior. No dispatch request or call was made; no provider setting was changed.

## Summary by verification layer

| Layer | Finding | Status |
|---|---|---|
| Backend value verified | The backend has a trusted server-side setting and fails closed unless its value is explicitly configured and marked verified. In the current workspace, the name setting is unset and the verification flag is unset/default false. No actual represented-business name is currently supplied. | **NOT CONFIGURED** |
| Provider payload mapping verified | When enabled and eligible with verified identity configured, backend context construction maps that setting to the exact key `verified_business_name`; the provider adapter passes it under SDK/API `call_context`. The remote welcome uses `{{verified_business_name}}`. | **VERIFIED IN CODE AND DOCUMENTED REQUEST SHAPE** |
| Provider documentation supports substitution | OmniDimension documents `{{variable_name}}` placeholders as substituted from dynamic-variable key/value data at call time, and documents dispatch `call_context` as key/value context passed to the agent during the call. | **DOCUMENTED BEHAVIOR SUPPORTS THE INTENDED MAPPING** |
| Actual provider-side substitution verified | No call or provider dispatch was made. The latest documented agent GET returned `dynamic_variables` as an empty array, not a map containing `verified_business_name`. The welcome placeholder is present remotely, but this evidence does not establish that this agent resolves the per-call `call_context` key at runtime. | **NOT VERIFIED** |

The distinction matters: backend mapping is verified, while runtime substitution for agent `261506` is not. Do not treat the mocked provider test as evidence of provider-side substitution.

## Backend flow and trusted value

Configuration fields in `app/core/config.py::Settings` are:

- `outbound_represented_business_name: str | None = None`
- `outbound_represented_business_identity_verified: bool = False`
- `outbound_calls_enabled: bool = False`

The current `.env` and process environment have neither `OUTBOUND_REPRESENTED_BUSINESS_NAME` nor `OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED` set. Therefore **the exact current business-name value is absent**; it is not inferred from a lead, scrape, remote agent name, or test fixture. The settings are trusted only as server-side configuration. The boolean is an administrative attestation and does not itself establish independent evidence.

`app/api/v1/calls.py::dispatch_outbound_call()` passes those server-side settings into `CallDispatchService`; `DispatchRequest` does not accept a business name, agent ID, or arbitrary call context. In `app/services/call_dispatch.py::CallDispatchService.run()`:

1. Lead/phone validation and eligibility run first.
2. Disabled mode returns `dry_run` before provider construction.
3. In enabled mode, a missing, blank, or unverified represented-business identity returns `represented_business_identity_unverified` before the provider factory is constructed.
4. `_call_context()` independently rejects an unverified or blank name, trims the configured value through `RepresentedBusinessContext`, and builds the validated model.

The current `OUTBOUND_CALLS_ENABLED` setting remains false: `.env` does not override it and `app/core/config.py` defaults it to `False`.

## Exact mapping

`app/models/call_dispatch.py::OutboundCallContext.to_provider_context()` flattens the validated fields and filters them against the dynamic-variable names declared in `outbound_agent_config()`:

```json
{
  "lead_business_name": "<validated lead business name, if available>",
  "verified_business_name": "<server-configured name, only after verification>",
  "contact_basis_status": "verified"
}
```

The local `_OUTBOUND["dynamic_variables"]["verified_business_name"]` value (`[CONFIGURE_VERIFIED_BUSINESS_NAME]`) is a template/allowlist placeholder, not the actual business identity. The dispatch service does not send the static `dynamic_variables` map or update the agent; it sends the per-call `call_context` only. The actual configured name would come from `OUTBOUND_REPRESENTED_BUSINESS_NAME` after an administrator verifies and sets it.

`lead_business_name` is sourced from the validated lead record; it is not used as the represented business identity. The destination phone is passed separately as normalized `to_number`. Other lead fields are not included in this provider context.

`app/services/call_dispatch.py::OmniDimensionDispatchProvider.dispatch_call()` forwards `call_context` to `client.call.dispatch_call(...)`. The installed SDK implementation in `.venv/Lib/site-packages/omnidimension/Call/__init__.py::Call.dispatch_call()` serializes it under the request-body key `"call_context"`, alongside `agent_id`, `to_number`, and `from_number_id`. No undocumented prompt field is added.

For agent `261506`, the latest read-only GET returned this welcome text:

> Hello! I'm an AI assistant calling on behalf of {{verified_business_name}}. Is this a convenient time to speak with you?

The exact placeholder spelling matches the backend context key. The GET returned `is_welcome_message_dynamic = true`, and `dynamic_variables` as an empty array (`[]`). This confirms the remote welcome contains the placeholder but does not demonstrate that a call-time value replaces it.

## Official provider documentation

- [Dispatch call API](https://docs.omnidim.io/docs/api-reference/calls/dispatchCall) documents `call_context` as optional key/value context passed to the agent during the call, and documents the request-body field.
- [Create agent API](https://docs.omnidim.io/docs/api-reference/agents/createAgent) documents `dynamic_variables` as a key/value map used to substitute placeholders in the prompt and welcome message at call time, with `{{variable_name}}` syntax.
- [Update agent API schema](https://docs.omnidim.io/docs/api-reference/agents/updateAgent) documents the same dynamic-variable placeholder behavior.

Taken together, these documented descriptions support the intended mechanism: the backend sends a key/value under `call_context`, and the agent welcome uses the matching `{{verified_business_name}}` placeholder. However, the documentation does not provide evidence that the current empty `dynamic_variables` GET state resolves this specific call-context value for agent `261506`, nor has a controlled authorized call been performed. Actual provider-side substitution is therefore **not verified**.

## Existing mocked tests reviewed

No test gap was found for the requested backend-side checks, so no tests were added.

- `tests/test_call_dispatch.py::test_eligible_lead_dispatches_and_sends_minimal_context` asserts the exact mocked provider context contains the synthetic lead business name, synthetic verified represented-business name, and `contact_basis_status="verified"`; it checks the context keys are declared by the local template.
- `tests/test_call_dispatch.py::test_missing_or_unverified_represented_business_blocks_enabled_dispatch` checks missing and unverified identity block before provider construction and dispatch.
- `tests/test_call_dispatch.py::test_missing_optional_lead_fields_are_omitted_from_call_context` checks omission of unavailable optional lead values.
- `tests/test_call_dispatch.py::test_dispatch_request_rejects_arbitrary_agent_id_and_context` checks callers cannot supply an agent ID or context.
- `tests/test_lead_management_api.py::test_authenticated_dispatch_route_runs_with_isolated_fixtures_and_mock_provider` checks route wiring with a mock, including identity verification and exact call context. Its enabled flag is a temporary in-memory test override; the actual configuration remains disabled.

These tests inspect the dictionary passed to a mock. They do not execute the OmniDimension SDK against the provider and do not prove placeholder substitution.

Tests were not executed for this audit. Prior environment checks found `python` unavailable and the virtual environment's configured Python 3.12 interpreter missing.

## Limitations and safety record

- There is no trusted represented-business name configured in the current environment, so a real enabled dispatch would be blocked by the identity check.
- The current agent GET exposed `dynamic_variables` as an empty array; the API documentation describes this setting as an object. Its provider-side meaning for call-time values is not established here.
- No provider dispatch or call was made, so actual welcome substitution remains unverified.
- Mocked tests verify backend construction and adapter arguments only.
- `OUTBOUND_CALLS_ENABLED` remains false. No provider settings, source files, database records, environment variables, scraper files, or lead data were modified.
