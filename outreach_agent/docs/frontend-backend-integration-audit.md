# LeadSutra AI Frontend and Backend Integration Audit

Audit date: 2026-10-04  
Backend: `D:\Leadsutra_AI\leadsutra_backend`  
Lead source configured by default: `D:\Leadsutra_AI\leads.json`

## Executive finding

No LeadSutra frontend application was present in the inspected project root. The sibling folder `D:\Leadsutra_AI\LeadSutra-AI` contains Python packages and tests, and its README describes Google Places Text Search; it has no frontend package manifest, JS/TS UI source, route definitions, style system, or UI tests. The backend also contains no frontend source. The available HTML files discovered under the separately named scraper project are scraper test fixtures, not an identified LeadSutra homepage or design reference. Therefore the frontend architecture, current pages, auth UI, and visual identity cannot be verified in this checkout; a frontend source location/design reference is needed before a no-redesign implementation can be planned at component level.

## 1. Frontend audit and project structure

### What was found

- `D:\Leadsutra_AI\LeadSutra-AI\` is a Python codebase with `app/`, `tests/`, `requirements.txt`, `test_api.py`, and `README.md`. The README describes the Google Places search phase. It is not a browser frontend.
- `D:\Leadsutra_AI\leadsutra_backend\` is the FastAPI backend. Its application folders are `app/api/v1`, `app/core`, `app/models`, and `app/services`; tests are under `tests/`.
- The backend exposes FastAPI/OpenAPI docs at `/docs` when running. This is backend API documentation, not a product frontend.
- No browser router, login/signup page, role-aware UI, dashboard, lead/campaign screens, frontend API utility, client-side state management, CSS design tokens, typography files, or frontend test suite was found in the inspected root.
- No product homepage HTML design reference was found in the backend or the Python `LeadSutra-AI` codebase. Scraper HTML fixtures are not a suitable design source.

### Frontend audit status

| Area requested | Finding |
|---|---|
| Framework/build tooling | Not present in inspected project roots; no `package.json`, Vite/Next/Angular config, or equivalent. |
| Routes/pages/layouts/navigation | Not found. |
| Authentication pages and RBAC | Not found in a frontend. Backend role-token checks are described below. |
| Dashboard, leads, campaigns | Not found. The backend has lead and call APIs, but that does not imply corresponding UI pages exist. |
| API utilities/state management/reusable components | Not found. |
| Design system/typography/colors | Not found. No UI redesign or component assumptions should be made until the actual frontend and design reference are supplied. |
| Frontend tests | None found. Backend tests are in `tests/` and cover API/service behavior. |

## 2. Backend architecture and source map

The API is mounted from `app/main.py` using the configured prefix, default `/api/v1`. Router registration is in `app/api/v1/router.py`. The lead JSON is read by `app/services/leads.py` using `lead_json_path`; lead response schemas live in `app/models/lead_management.py` and `app/models/leads.py`. Eligibility and suppression persistence/checks are in `app/services/calling_eligibility.py`; request/response models are in `app/models/calling_eligibility.py`. Dispatch behavior and SQLite ledger are in `app/services/call_dispatch.py`, with request/result enums in `app/models/call_dispatch.py`. Call history uses the same dispatch ledger; its projection model is `app/models/call_history.py`. Follow-ups use `app/services/follow_ups.py` and the same model module. Environment settings are in `app/core/config.py` and `.env.example`.

SQLite file default: `data/calling_eligibility.sqlite3` (`ELIGIBILITY_DB_PATH`). Lead source default: `D:\Leadsutra_AI\leads.json` (`LEAD_JSON_PATH`). The backend does not write to the lead JSON source.

## 3. Authentication and authorization verified in source

`app/api/v1/calling_eligibility.py` defines `HTTPBearer` authentication and `require_reviewer` / `require_admin` dependencies. A configured token must be at least 32 characters. Comparisons use `hmac.compare_digest`. If required credentials are missing/too short, protected calls fail with 503; a missing or incorrect bearer credential returns 401.

- Admin endpoints accept only `ELIGIBILITY_ADMIN_TOKEN`.
- Reviewer endpoints accept `ELIGIBILITY_REVIEWER_TOKEN`, falling back to the admin token when the reviewer token is unset. Thus an admin can use reviewer-authorized routes.
- The backend does not authenticate end users, issue sessions/JWTs, map identities from an identity provider, or perform per-user RBAC. `_principal` returns a role label (`eligibility-admin` / `eligibility-reviewer`), not an account identity. This is why follow-up `assigned_reviewer` is currently null.
- The backend README (`README.md`) likewise says frontend authentication is not implemented and advises a trusted gateway/backend-for-frontend. This is corroborated by the actual auth code.
- The health/root/OmniDimension connection endpoints currently have no auth dependency. The connection endpoint returns only coarse connected/error state but performs an OmniDimension connectivity check using the server-side key.

**Security consequence:** Never embed either bearer token or `OMNIDIM_API_KEY` in frontend source, browser storage, build-time `VITE_*`/`NEXT_PUBLIC_*` variables, or requests sent directly from an untrusted browser. Hiding admin controls is not authorization. Use an authenticated server-side BFF or trusted gateway that authenticates the person, authorizes their role on every request, and injects the backend reviewer/admin token server-side. Keep provider and backend credentials in server environment/secret storage. The frontend should hold only its normal user session (preferably Secure, HttpOnly, SameSite cookies at the BFF); protect cookie-authenticated writes against CSRF. Restrict CORS to the deployed frontend origins; CORS is not authentication.

## 4. Backend endpoint inventory

All paths below are relative to `/api/v1` unless explicitly marked. Schema field lists are taken from endpoint function signatures and Pydantic models in the referenced source. `Authorization` means `Authorization: Bearer <configured role token>`.

### Status and integration

| Method/path | Request | Response/behavior | Auth | Source |
|---|---|---|---|---|
| `GET /health` (outside API prefix) | None | `{status, application, environment, api_version}` | Public | `app/main.py` |
| `GET /` | None | `{version, status}`; currently `status: "available"` | Public | `app/api/v1/router.py` |
| `GET /integrations/omnidimension/connection` | None | Success `{status: "connected", provider: "omnidimension"}`; missing key 503; failed check 502 with sanitized detail | Public | `app/api/v1/router.py`, `app/services/omnidimension.py` |

### Leads

All lead reads below require reviewer bearer auth. Lead list/detail project only backend-approved fields and normalize supported Indian mobiles.

| Method/path | Request/query | Response | Source |
|---|---|---|---|
| `GET /leads` | Query: `limit` (1–100, default 25), `offset` (0–1,000,000, default 0), `search` (max 200), `qualification_status` (max 100), `category` (max 100) | `{total, limit, offset, leads:[{lead_id, business_name, category, qualification_status, lead_score, phone_numbers[]}]}` | `app/api/v1/leads.py`, `app/models/lead_management.py` |
| `GET /leads/preview` | None | `{total, eligible, rejected, manual_review, dispatch_enabled:false, leads:[PreparedLead...]}`. This legacy preview includes more source-derived detail, including email addresses, original/invalid phone data, and eligibility reasons. | `app/api/v1/leads.py`, `app/models/leads.py` |
| `GET /leads/{lead_id}` | Path `lead_id` (1–256 chars) | `{lead_id, business_name, website, category, address, contact_names[], phone_numbers[], lead_score, qualification_status}`. Current source model does not contain contact names, so the field is empty. | `app/api/v1/leads.py`, `app/models/lead_management.py` |
| `GET /leads/{lead_id}/calls` | Query `limit` (1–100, default 25), `offset` (0–1,000,000, default 0) | `CallHistoryPage` for that lead; 404 when lead does not exist. | `app/api/v1/leads.py`, `app/models/call_history.py` |

### Calling eligibility, consent, suppression, and telecom attestations

| Method/path | Request/query | Response/behavior | Auth | Source |
|---|---|---|---|---|
| `GET /calling-eligibility/{lead_id}` | Query required: `phone_number` | `{eligible, reason_codes[], checked_at, lead_id, normalized_phone_number}`; uses server-configured purpose and fail-closed checks | Reviewer | `app/api/v1/calling_eligibility.py`, `app/models/calling_eligibility.py` |
| `PUT /calling-eligibility/consent` | JSON `ConsentRecordInput`: `lead_id`, `phone_number`, `consent_status` (`verified`, `unknown`, `denied`, `revoked`, `pending_verification`, default unknown), optional `consent_scope`, `consent_source`, `evidence_reference`, `recorded_at`, `verified_at`, `verified_by`, `expiry_at`, `revoked_at`. Extra fields forbidden; timestamps require timezone. Verified requires scope/source/evidence reference; revoked requires `revoked_at`. | `ConsentStatusResponse`: lead/phone/status/scope/source/recorded and verification timestamps/verifier/expiry/revocation. Evidence reference is not returned. | Admin | `app/api/v1/calling_eligibility.py`, `app/models/calling_eligibility.py` |
| `GET /calling-eligibility/consent/{lead_id}?phone_number=...` | Path lead and required phone query | Consent status above; unknown record returns status `unknown` and null optional fields. | Admin | Same |
| `PUT /calling-eligibility/suppression` | JSON `{phone_number, suppression_status}` where status is `suppressed`, `not_suppressed`, or `unknown` (default `suppressed`); optional `reason` | `{phone_number, suppression_status, reason, updated_at}` | Admin | Same |
| `GET /calling-eligibility/suppression?phone_number=...` | Required phone query | Suppression response; absent record returns `unknown`. | Admin | Same |
| `PUT /calling-eligibility/telecom-checks` | JSON `TelecomCheckInput`: `lead_id`, `phone_number`, `preference_status`, `route_status` (each `approved`, `denied`, `unknown`; default unknown), `provider_reference`, `calling_hours_status`, `attempts_used` (>=0), `attempt_limit` (>0). Approval requires provider reference. | HTTP 204 | Admin | `app/api/v1/calling_eligibility.py` |

The app does **not** perform DND lookup or authorized telecom-route verification itself; these are externally attested checks recorded by the admin endpoint. Do not portray this endpoint as a live telecom integration.

### Dispatch and call history

| Method/path | Request/query | Response/behavior | Auth | Source |
|---|---|---|---|---|
| `POST /calls/dispatch` | JSON, extra fields forbidden: `{lead_id, phone_number, idempotency_key}` where key is UUID | `DispatchResult`: `{status, eligible, dispatched, dispatch_enabled, lead_id, normalized_phone_number, agent_id, reason_codes[], provider_request_id}`. `status` values: `blocked`, `dry_run`, `dispatching`, `dispatched`, `duplicate`, `provider_error`, `uncertain`. With `OUTBOUND_CALLS_ENABLED=false`, an otherwise eligible request is `dry_run`, `dispatched:false` and does not construct/use the provider client. | Admin | `app/api/v1/calls.py`, `app/models/call_dispatch.py`, `app/services/call_dispatch.py` |
| `GET /calls` | Optional `lead_id`; optional `dispatch_status` from `DispatchStatus`; `limit` (1–100, default 25); `offset` (0–1,000,000, default 0) | `{total, limit, offset, calls:[CallHistoryItem...]}` | Reviewer | `app/api/v1/calls.py`, `app/models/call_history.py` |
| `GET /calls/{call_id}` | Path `call_id` UUID | `CallHistoryItem`: `{call_id, lead_id, phone_number, dispatch_status, provider_request_id, dispatch_requested, provider_accepted, call_outcome, created_at, updated_at}`. `call_outcome` is currently always `unknown`. | Reviewer | Same |

`dispatched`/`provider_accepted:true` means dispatch was accepted by the provider API; it does not establish that the recipient answered or that a call completed. History is sourced from the idempotency ledger. `call_id` in this API is the internal dispatch UUID, not an OmniDimension call ID. There is no confirmed outcome/transcript persistence yet because webhook integration is pending.

### Follow-ups

All follow-up routes require reviewer bearer auth.

| Method/path | Request/query | Response/behavior | Source |
|---|---|---|---|
| `POST /follow-ups` | JSON, extra fields forbidden: `{lead_id, related_call_id? (UUID), scheduled_at (timezone-aware datetime), notes? (max 4000), idempotency_key (UUID)}` | `FollowUpRecord`: `{follow_up_id, lead_id, related_call_id, scheduled_at, status, assigned_reviewer, notes, idempotency_key, created_at, updated_at}`; HTTP 201. Status starts `pending`. Idempotent retries return the original record. Lead must exist; a related internal call UUID must exist and have that lead ID. | `app/api/v1/follow_ups.py`, `app/models/call_history.py`, `app/services/follow_ups.py` |
| `GET /follow-ups` | Optional `lead_id`, optional `status` (`pending`, `completed`, `cancelled`), `limit` (1–100, default 25), `offset` (0–1,000,000, default 0) | `{total, limit, offset, follow_ups:[FollowUpRecord...]}` | Same |
| `GET /follow-ups/{follow_up_id}` | UUID path | `FollowUpRecord`; 404 if missing | Same |
| `PATCH /follow-ups/{follow_up_id}` | JSON patch with optional `scheduled_at`, `status`, `notes`; extra fields forbidden | Updated `FollowUpRecord`. Pending may become completed or cancelled. Terminal records cannot be reopened/re-transitioned or rescheduled. Schedule timestamps must have a timezone. | Same |

All persisted datetimes are ISO timestamps normalized to UTC where written. `assigned_reviewer` is null: current backend authentication cannot identify an individual reviewer.

## 5. Current integration gaps

1. **Frontend source is missing from the inspected checkout.** Need its actual repository/path and homepage/design reference before auditing its visual identity, route tree, auth, state management, and reusable components or mapping onto existing pages.
2. **No end-user auth/session layer exists in this backend.** Current role credentials are static server configuration tokens. A BFF/gateway and identity-to-role policy must be selected and implemented before a browser can securely use protected endpoints.
3. **Static bearer tokens are role-wide, not per-user.** No audit trail can attribute consent/follow-up actions to a user identity. Follow-up reviewer is null.
4. **Direct browser integration is unsafe.** Putting backend role tokens or OmniDimension key in a SPA exposes privileged credentials. Endpoint-level auth remains required even if the UI hides controls.
5. **Connection status is public.** Decide whether to restrict it at a gateway if the service is Internet-facing.
6. **Call results remain unknown.** Pending Module 3F provider webhook prevents actual result, transcript, duration, recording, and confirmed outcome displays. Frontend must render these as unavailable/unknown, not infer them from dispatch status.
7. **Call history only represents ledger entries.** Dry runs and preflight rejections before a ledger claim are not historical records; provider request ID is not documented/mapped to provider call ID here.
8. **UI design cannot be assessed.** There are no verified product color/typography/token assets or existing pages to preserve in the located source.

## 6. Recommended frontend API architecture

Use a server-side BFF or trusted API gateway as the only browser-facing integration boundary:

1. Authenticate users with the product identity provider/application session; do not pass backend bearer tokens to the browser.
2. On each request, authorize a role/permission (for example `leads:read`, `eligibility:read`, `consent:manage`, `calls:read`, `calls:dispatch`, `followups:manage`). Map permissions to reviewer/admin backend calls server-side. Only a tightly authorized operator should receive admin capability; role checks must happen server-side.
3. Keep reviewer/admin tokens and `OMNIDIM_API_KEY` in server secrets. Use secure session cookies and CSRF defenses if BFF auth is cookie-based. Apply same-origin routing where possible and a narrow CORS allowlist.
4. Create typed API modules grouped by `leads`, `eligibility`, `consent/suppression`, `calls`, `followUps`, and `system`. Each should own URL construction, query serialization, response validation, error translation, and cancellation/timeouts.
5. Treat server output as authoritative. Never submit client-supplied `eligible`, consent state, purpose, agent ID, provider context, or call outcome. Dispatch body only accepts lead ID, phone, and UUID idempotency key.
6. Use query caching/invalidation for lists/details; invalidate lead calls after dispatch and follow-up lists/details after mutations. Preserve pagination values from API results.
7. Render status distinctions explicitly: eligibility is a preview, `dry_run` is no dispatch, `dispatched` is provider acceptance, and call outcome stays unknown pending verified result integration.

## 7. Recommended page-to-endpoint mapping

This maps backend capabilities to future screens only; no corresponding frontend pages were found.

| Future screen/workflow | Endpoints |
|---|---|
| Operations health/status | `GET /health`, `GET /api/v1/`; expose OmniDimension connectivity only to authorized operators or gateway policy via `GET /api/v1/integrations/omnidimension/connection`. |
| Lead list/search/detail | `GET /api/v1/leads` with pagination/search/qualification/category; `GET /api/v1/leads/{lead_id}`. Avoid `/leads/preview` for routine UI because it contains a broader source projection. |
| Lead calling readiness | `GET /api/v1/calling-eligibility/{lead_id}?phone_number=...`; admin-only consent/suppression review/write endpoints only where role policy grants it. |
| Consent and telecom operations | `PUT/GET /api/v1/calling-eligibility/consent...`, `/suppression`, `PUT /telecom-checks`; BFF must enforce admin permission. Explain external-attestation semantics and never imply the app performed DND checks. |
| Call dispatch panel | `POST /api/v1/calls/dispatch` only through admin-authorized BFF. With current setting false, label response as dry run. Require one idempotency UUID per intent and reuse it on transport retry. |
| Call history/detail | `GET /api/v1/calls` with pagination/status/lead filters; `GET /api/v1/calls/{call_id}`; lead detail can use `GET /api/v1/leads/{lead_id}/calls`. Show `call_outcome: unknown` honestly. |
| Follow-up queue/detail | `GET /api/v1/follow-ups` with pagination/status/lead filters and `GET /api/v1/follow-ups/{id}`. |
| Follow-up create/edit/complete/cancel | `POST /api/v1/follow-ups` and `PATCH /api/v1/follow-ups/{id}`. Supply timezone-aware `scheduled_at` and stable idempotency UUID. |

## 8. Sequential Modules 4B–4E plan

### Module 4B — Locate and establish secure app boundary

- Obtain the actual frontend repository/path and approved homepage/design reference; rerun its audit before UI work.
- Choose user identity provider and document reviewer/admin permission policy.
- Implement or select a trusted BFF/gateway. Store backend tokens only server-side; add server-side authorization, session/CSRF protections as applicable, rate limiting, and narrow CORS/network exposure.
- Decide how the public connection check is restricted for deployment. Keep `OUTBOUND_CALLS_ENABLED=false`.

### Module 4C — Frontend foundation and API contract layer

- In the actual existing frontend, preserve its router, design tokens, layouts, and components; do not replace them with a generic dashboard.
- Add typed API client modules against the verified request/response schemas in this audit and backend OpenAPI.
- Add session-aware error/loading/empty states and permission handling without placing backend tokens in browser bundles.
- Add contract tests/mocks for auth, 401/403/503, pagination, and backend validation errors.

### Module 4D — Leads and compliance workflow

- Wire existing or approved lead views to lead list/detail APIs.
- Add contact-specific eligibility preview and appropriately permissioned consent/suppression/telecom operations.
- Keep unknown/unverified states blocked and explain that telecom/DND status is externally attested.
- Test role enforcement server-side and verify public phone data never appears as consent.

### Module 4E — Dispatch, history, and follow-up workflow

- Add protected dispatch UI with explicit dry-run behavior, idempotency handling, and no browser-supplied eligibility claims. Keep live outbound calling disabled.
- Add history and follow-up screens using the exact ledger/follow-up schemas, filters, paging, and allowed transitions.
- Display provider acceptance separately from call result; leave result/transcript fields unavailable until a verified Module 3F webhook integration exists.
- Add end-to-end tests through the BFF/gateway, permission tests for reviewer/admin boundaries, and UI regression tests against the approved design reference.

## 9. Files inspected

Backend source/schema/auth/config/docs inspected: `app/main.py`, `app/api/v1/router.py`, `app/api/v1/leads.py`, `app/api/v1/calls.py`, `app/api/v1/follow_ups.py`, `app/api/v1/calling_eligibility.py`, `app/models/lead_management.py`, `app/models/leads.py`, `app/models/call_dispatch.py`, `app/models/call_history.py`, `app/models/calling_eligibility.py`, `app/services/call_dispatch.py`, `app/services/calling_eligibility.py`, `app/services/follow_ups.py`, `app/services/leads.py`, `app/services/omnidimension.py`, `app/core/config.py`, `.env.example`, `README.md`, and backend `tests/` file inventory.

Frontend-location discovery inspected the project root inventory and file manifests/types under `D:\Leadsutra_AI`, excluding dependency/build output. The README in `D:\Leadsutra_AI\LeadSutra-AI` identifies that Python project as Google Places search. The scraper project was not modified; its HTML fixture files were excluded as design references.

## Uncertainties

- The actual frontend may be in a different repository or path not present under `D:\Leadsutra_AI`; obtain that location before claiming its architecture/design was audited.
- No user identity provider, product role policy, or BFF deployment target is configured in backend source, so the proposed server-side auth mapping remains a design recommendation, not existing functionality.
- OmniDimension webhook result delivery remains pending; available call results are limited to the dispatch ledger semantics documented above.
