# LeadSutra AI Backend

Foundation for the LeadSutra AI application backend. The repository root is
used as the project root because this workspace is already dedicated to the
backend; an extra `backend/` directory would add unnecessary nesting.

## Requirements

- Python 3.12
- pip

The dependency ranges in `requirements.txt` are compatible with Python 3.12.
This workspace did not have an accessible Python executable during initial
setup, so the local interpreter and installed package versions could not be
verified here.

## Create a virtual environment

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

## Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configure environment

Copy `.env.example` to `.env` and edit the values as needed. Settings are read
from environment variables, with `.env` used for local development. For
`CORS_ORIGINS`, provide a JSON list, for example:

```dotenv
CORS_ORIGINS=["http://localhost:3000"]
```

No credentials are required for this foundation.

To enable the OmniDimension connectivity check, set `OMNIDIM_API_KEY` in `.env`
or the process environment. The server still starts when this value is absent.

## Start the server

```bash
uvicorn app.main:app --reload
```

Health check: `GET http://127.0.0.1:8000/health`

Versioned API root: `GET http://127.0.0.1:8000/api/v1/`

OmniDimension connectivity: `GET http://127.0.0.1:8000/api/v1/integrations/omnidimension/connection`

The connectivity endpoint returns `200` with `{"status":"connected","provider":"omnidimension"}` on success, `503` when the key is missing, and `502` when the SDK check fails. It never returns agent data or SDK error details.

## Run tests

```bash
python -m pytest
```

The tests cover application import/startup, the health response, and the
versioned router registration.

## Lead preview integration

`GET /api/v1/leads/preview` reads the configured JSON array (read-only), validates
Indian mobile numbers, and reports each lead's eligibility. Set `LEAD_JSON_PATH`
to the JSON file; development defaults to `D:\Leadsutra_AI\leads.json`.
Eligibility is not consent: consent/lawful-basis and suppression checks remain
unapproved by default, and the response always reports `dispatch_enabled: false`.
This endpoint only previews data and never initiates calls.

## Calling eligibility (dispatch remains disabled)

The authenticated `/api/v1/calling-eligibility` endpoints store consent,
suppression, and privileged compliance attestations in SQLite. Configure
`ELIGIBILITY_ADMIN_TOKEN` and `ELIGIBILITY_REVIEWER_TOKEN` with distinct,
random values of at least 32 characters before use. Admin access is required
to record/review consent, update/review suppression, and record telecom and
operational check results. The reviewer token can preview eligibility. If no
reviewer token is set, the admin token can also preview.

Consent defaults to `unknown`; only verified consent with a matching purpose,
evidence reference, source, and verifier passes. Suppression takes precedence.
Unknown or stale telecom checks, calling-hours assessments, or attempt limits
block eligibility. Approval states must be supplied by a real authorized
telecom/compliance workflow. The backend does not query DND and does not treat
a public business listing as permission to call. Consent evidence references
are never returned by the review or eligibility endpoints. Eligibility
approval alone never initiates a call.

## Outbound dispatch (disabled by default)

`POST /api/v1/calls/dispatch` requires the admin bearer token and accepts a
lead ID, one of that lead's normalized phone numbers, and a caller-generated
UUID idempotency key. It does not accept an agent ID or consent purpose from
the client. The configured purpose defaults to `commercial_sales_call`, and
the configured agent ID defaults to `261506`.

`OUTBOUND_CALLS_ENABLED=false` keeps the endpoint in eligibility-checked dry
run mode and prevents all OmniDimension requests. Enabling it permits provider
dispatch only after two successful eligibility evaluations and live
verification that the configured agent is outbound. The backend ledger blocks
reuse of an idempotency key and retains uncertain outcomes to prevent an
automatic retry. OmniDimension's documented endpoint does not expose a
provider-side idempotency key, so callers must reuse the same UUID when retrying
an HTTP request. A new UUID represents a new dispatch attempt.

Enabled dispatch also requires an explicit represented-business name configured
as `OUTBOUND_REPRESENTED_BUSINESS_NAME` and
`OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED=true`. Set the verification
flag only after an authorized operator has verified that identity. The defaults
are unset/false; without both values, enabled dispatch is blocked. These values
are server-side settings and cannot be supplied by an API caller. Keep
`OUTBOUND_CALLS_ENABLED=false` until the verified represented-business identity
and live agent configuration have been reviewed.

Dispatch uses the installed SDK's `client.call.dispatch_call(agent_id,
to_number, call_context=...)`, which posts to OmniDimension's documented
`POST /api/v1/calls/dispatch` endpoint with SDK bearer authentication. The
context is built from a validated model and the outbound template's declared
dynamic-variable names. It contains only the lead business name when present,
the server-configured verified represented-business name, and
`contact_basis_status=verified` after eligibility passes. The normalized
destination phone is sent separately as `to_number`. The API key, consent
evidence references, email, internal lead score, and arbitrary frontend context
are not sent. Agent instructions remain in the local outbound configuration
template; no undocumented per-call prompt field is sent. See
[`docs/outbound-agent-integration.md`](docs/outbound-agent-integration.md) for
the integration contract and limitations.

## Lead workflow APIs

These routes are documented in Swagger at `/docs`. Lead reads and eligibility
preview require the reviewer bearer token. Dispatch requires the admin bearer
token. Do not place either configured token in browser code or ship it to the
frontend. Frontend authentication is not implemented in this backend yet; a
trusted application API gateway or backend-for-frontend must authenticate the
user and attach the corresponding backend role token. No public or temporary
authentication bypass is provided.

```http
GET /api/v1/leads?limit=25&offset=0&search=cafe&qualification_status=Qualified&category=Restaurant
Authorization: Bearer <REVIEWER_TOKEN>
```

Example list response:

```json
{
  "total": 1,
  "limit": 25,
  "offset": 0,
  "leads": [
    {
      "lead_id": "lead-123",
      "business_name": "Example Cafe",
      "category": "Restaurant",
      "qualification_status": "Qualified",
      "lead_score": 73.0,
      "phone_numbers": ["+919876543210"]
    }
  ]
}
```

`GET /api/v1/leads/{lead_id}` returns the business website, category, address,
normalized phones, score, and qualification. The current validated lead model
does not represent contact names, so `contact_names` is an empty list. Email,
raw invalid phone values, consent evidence, and internal records are omitted.
`GET /api/v1/leads/preview` remains a protected legacy import preview.

Use `GET /api/v1/calling-eligibility/{lead_id}?phone_number=%2B919876543210` for
selected-lead eligibility. It uses the backend-configured purpose and shared
fail-closed evaluator. Eligibility filtering is not offered on the list route:
eligibility is contact-specific and depends on multiple changing SQLite
records, so it is evaluated only for a selected lead and phone.

Example eligibility response:

```json
{
  "eligible": false,
  "reason_codes": ["consent_unknown", "suppression_unknown"],
  "checked_at": "2026-10-04T12:00:00Z",
  "lead_id": "lead-123",
  "normalized_phone_number": "+919876543210"
}
```

Dispatch preview/submit uses the existing protected endpoint:

```http
POST /api/v1/calls/dispatch
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "lead_id": "lead-123",
  "phone_number": "+919876543210",
  "idempotency_key": "9e3cad9f-e623-4b2c-8fc9-ceaa71ef9e01"
}
```

With the default disabled setting, an eligible response has `status: "dry_run"`,
`eligible: true`, `dispatched: false`, and `dispatch_enabled: false`. An
ineligible request returns `status: "blocked"` and reason codes; frontend
eligibility values are never accepted as input. The client cannot select the
agent, consent purpose, or provider context.

Example dry-run response:

```json
{
  "status": "dry_run",
  "eligible": true,
  "dispatched": false,
  "dispatch_enabled": false,
  "lead_id": "lead-123",
  "normalized_phone_number": "+919876543210",
  "agent_id": 261506,
  "reason_codes": ["provider_dispatch_disabled"],
  "provider_request_id": null
}
```
