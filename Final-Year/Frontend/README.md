# LeadSutra AI frontend foundation

React, TypeScript and Vite application with a responsive shared shell, reusable UI components, existing sales-workspace pages, and a centralized Axios client. The interface uses the LeadSutra blue and warm-white design tokens in `src/brand.css`.

## Run locally

Start the backend first from `D:\Final Year\Backend`:

```powershell
python run.py
```

Then start the frontend from this directory:

```sh
npm ci
npm run dev
```

In development, leave `VITE_API_BASE_URL` unset or set it to `/` so Vite proxies `/api` requests to `http://127.0.0.1:8000`. This keeps the HttpOnly session cookie same-origin with the frontend; do not point the browser directly at `http://127.0.0.1:8000` when the frontend is on `http://localhost:5173`. For a deployed build, set `VITE_API_BASE_URL` to a trusted same-origin API/BFF. Never put backend bearer tokens, provider keys, or other secrets in `VITE_*` variables.

## Checks

```sh
npm run typecheck
npm run build
```

## Authentication and authorization

The frontend uses the backend registration and login routes. The backend stores accounts in MongoDB, hashes passwords with Argon2, and issues expiring JWT sessions in HttpOnly cookies. Session cookies are sent with same-origin API calls and are never copied to local/session storage. All API feature routes require a valid session; reviewer/admin operations retain their additional server-side token check. Set `AUTH_COOKIE_SECURE=true` when serving the app over HTTPS.

## Backend API connection

The frontend discovery client is wired to this workspace's FastAPI routes:

- `POST /api/v1/leads/discover` runs discovery, enrichment, scoring, and lead persistence. The UI submits the backend's `query`, `location`, and `limit` contract and renders the canonical lead response.
- `GET /api/v1/leads` lists stored leads; `GET /api/v1/leads/{lead_id}` loads one. Both require a signed-in user session.
- Call history, eligibility, and dispatch clients use `/api/v1/calls` and `/api/v1/calling-eligibility`. Those protected endpoints also require reviewer/admin authentication.

Do not put reviewer/admin tokens in browser storage or `VITE_*` values. Backend CORS allows the two default local Vite origins; set `CORS_ALLOWED_ORIGINS` to a comma-separated list of exact trusted origins when calling the API directly from another frontend origin.

The frontend only exposes features for which this backend has a matching route. Its schema does not provide dashboard aggregates, lead activity history, or competitor data; those are not inferred from discovery results.

## Main structure

```text
src/
  components/       layout, shared, and reusable UI
  config/           centralized navigation
  context/          backend-backed authentication session context
  hooks/            reusable app hooks
  pages/            landing, login/signup, dashboard, leads, discovery, outreach, and settings
  services/         API client, feature clients, and backend auth client
  types/            shared TypeScript types
  utils/            API error and class helpers
  brand.css         LeadSutra visual tokens and theme overrides
```
