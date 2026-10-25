# LeadSutra AI Backend

Autonomous backend engine for **lead discovery, enrichment, qualification, scoring, voice calling, and email outreach**.

## 🚀 Quick Start

Run the following commands from the `backend` directory.

**Install dependencies** (use your own Python environment if you have one; this project does not create one):

```powershell
python -m pip install -r requirements.txt
```

**Install the browser** if using Google Maps browser discovery or fallback (once per machine):

```powershell
python -m playwright install chromium
```

**Start the server**

```powershell
python run.py
```

**API server:** http://127.0.0.1:8000  
**Interactive API docs:** http://127.0.0.1:8000/docs

## 🛠️ Technology Stack

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | `0.142.2` | API framework |
| `uvicorn` | `0.54.0` | ASGI server |
| `pydantic` | `2.13.5` | Request validation and data schemas |
| `pydantic-settings` | `2.15.0` | Environment-based configuration |
| `httpx` | `0.28.1` | Asynchronous HTTP client |
| `playwright` | `1.63.0` | Browser automation and dynamic scraping |
| `beautifulsoup4` | `4.15.0` | HTML parsing and website enrichment |
| `omnidimension` | `0.4.2` | Voice calling provider SDK |
| `python-dotenv` | `1.2.4` | Environment variable loading |
| `requests` | `2.34.2` | HTTP client library |
| `pymongo` | `4.x` | MongoDB document persistence |

## ⚙️ Environment Configuration

Configure environment variables in `Backend/.env`. Copy `.env.example` as a starting point; set `MONGODB_URI=mongodb://localhost:27017` for a local MongoDB server or use your MongoDB Atlas connection string. MongoDB and `AUTH_JWT_SECRET` (at least 32 characters) are required; the API fails startup if either is missing or MongoDB cannot be reached. Never commit `.env`.

| Setting | Default | Description |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated exact frontend origins allowed to call the API |
| `LEADSUTRA_ENABLE_GOOGLE_PLACES` | `true` | Enable Google Places API discovery |
| `LEADSUTRA_ENABLE_MAPS_BROWSER` | `true` | Enable Playwright-based Maps scraping |
| `LEADSUTRA_ENABLE_MAPS_BROWSER_FALLBACK` | `false` | Use browser scraping after retryable Places API errors |
| `LEADSUTRA_MAPS_FALLBACK_ON_ZERO_RESULTS` | `false` | Use browser scraping when Places returns zero leads |
| `LEADSUTRA_COMPETITOR_RADIUS_METERS` | `10000` | Maximum distance for same-category competitor listings, measured from the lead's Google Maps coordinates |
| `OUTBOUND_CALLS_ENABLED` | `false` | Enable live voice call dispatch |
| `EMAIL_SENDING_ENABLED` | `false` | Enable live SMTP email sending |
| `MONGODB_URI` | unset | MongoDB URI; e.g. `mongodb://localhost:27017` or an Atlas SRV URI |
| `MONGODB_DATABASE` | `leadsutra` | Database name |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS` | `5000` | Startup connection timeout |
| `AUTH_JWT_SECRET` | unset | Required signing secret for short-lived user sessions; use a unique random value of 32+ characters |
| `AUTH_COOKIE_SECURE` | `false` | Set `true` behind HTTPS in production |
| `LOG_FILE_PATH` | `Backend/logs/backend.log` | Rotating backend log file path |
| `LOG_LEVEL` | `INFO` | Backend log level |

With `LLM_PROVIDER=hybrid`, research uses the local `phi3:latest` model and proposal generation uses Groq's `openai/gpt-oss-120b` model by default. Configure `GROQ_API_KEY` and `PROPOSAL_PROVIDER=groq` in `Backend/.env`; proposal requests use low reasoning effort and a 4,096-token completion budget so reasoning leaves room for the required JSON response. Groq latency depends on network conditions and account limits. Research limits website enrichment to two pages/five seconds and indexes RAG knowledge after returning the API response. These settings target a 30–60 second research response, but actual latency depends on machine load and model output. Adjust `OLLAMA_RESEARCH_MODEL` and `OLLAMA_RESEARCH_NUM_PREDICT` to change the research speed/quality tradeoff.

Email preview, approval, send, and history routes use the signed-in workspace session; they do not require a separate admin token. Sending remains gated by explicit approval of the exact draft and enabled SMTP settings. Email previews also require a valid `SMTP_FROM_ADDRESS`, even when sending is disabled.

The application verifies MongoDB during startup and stores accounts, lead results, discovery-run snapshots, workflows, proposals, research, email results/approvals, call dispatch history, and consent records in MongoDB collections. Existing SQLite email/call/consent records are imported once; existing lead JSON, proposal, research, and workflow files are imported on access. New application results are written to MongoDB only. The Chroma vector index remains a separate retrieval index. Backend logs rotate at 5 MB and retain five backups.

User accounts are created with `POST /api/v1/auth/signup`, authenticated with `POST /api/v1/auth/login`, and inspected with `GET /api/v1/auth/me`. Sessions are signed, expiring JWTs in `HttpOnly`, `SameSite=Lax` cookies; the frontend does not store session tokens in JavaScript storage. All API feature routes require a valid signed-in session. Existing admin/reviewer operations keep their additional server-side reviewer/admin token checks.

For local development, run the backend on port `8000` and the Vite frontend on port `5173`. Vite proxies `/api` requests to the backend. If the frontend calls the backend directly from another origin, add that exact origin to `CORS_ALLOWED_ORIGINS` and restart the backend.

### Gmail SMTP Configuration

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_16_character_app_password
SMTP_FROM_ADDRESS=your_email@gmail.com
SMTP_TIMEOUT_SECONDS=15
EMAIL_SENDING_ENABLED=true
```

> **Security:** Use a Google App Password generated after enabling 2-Step Verification. Do not commit `.env`, passwords, API keys, or tokens to GitHub. Keep `.env.example` limited to placeholder values.

## 📦 Project Structure

```text
app/
├── agents/
│   ├── lead_pipeline/    # agent.py, pipeline.py, schema.py, scoring.py
│   ├── orchestrator/     # agent.py and workflow schema.py
│   ├── proposal/         # agent.py, prompt.py, schema.py
│   ├── rag/              # Retrieval agent and request schema
│   ├── research/         # agent.py, prompt.py, schema.py
│   ├── email/            # Email agent and request/result schemas
│   └── voice/            # Voice agent, prompt loader, and call schema
├── api/
│   ├── router.py         # Master API router
│   └── v1/               # Versioned API endpoints
├── core/
│   └── config.py         # Application settings
├── database/
│   └── mongodb.py        # Shared MongoDB connection and collection indexes
├── auth.py               # Password hashing and signed user-session cookies
├── models/
│   └── leads.py          # Lead validation and calling-eligibility representations
├── integrations/
│   ├── google_places.py  # Google Places API client
│   ├── maps_scraper.py   # Playwright Maps scraper
│   ├── website_fetcher.py# Website crawling and HTML parsing
│   ├── omnidimension.py  # Voice provider integration
│   └── smtp.py           # SMTP integration
├── schemas/              # Shared call and calling-eligibility API contracts
├── services/             # MongoDB persistence and workflow orchestration
└── utils/                # Safe HTTP transport and DNS protection
```

## 🔍 API Overview

### Independent AI Agents and Orchestrated Workflow

Research, knowledge retrieval, and proposal generation can be called separately. The workflow endpoints also orchestrate discovery, lead selection, research, RAG, proposal generation, human approval, and explicitly authorized outreach.

| Endpoint | Input | Output |
|---|---|---|
| `POST /api/v1/research/analyze` | A discovered lead object, or `{ "lead_id": "..." }` | Grounded business research |
| `POST /api/v1/research/competitors/{lead_id}` | Saved lead ID; optional `?refresh=true` | Cached or fresh nearby listings for the same category/location, with ratings, addresses, source, and a factual comparison |
| `POST /api/v1/rag/retrieve` | `{ "query": "...", "k": 3 }` | Matching knowledge documents and sources |
| `POST /api/v1/proposals/generate` | A lead object or lead ID; optional `research` and `retrieved_context` | Outreach angle, email subjects and draft, call opener, discovery questions, and proposal details |
| `POST /api/v1/leads/discover` | Search query, location, optional limit and priority | Discovered, enriched, qualified leads |
| `POST /api/v1/auth/signup`, `POST /api/v1/auth/login` | User credentials | Creates an account or signs in using a secure cookie |
| `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` | Current session | Restores or ends the signed-in session |
| `GET /api/v1/leads` | Optional search and pagination filters | Stored MongoDB lead page (signed-in session required) |
| `GET /api/v1/leads/{lead_id}` | Lead ID | One stored lead |
| `POST /api/v1/leads/{lead_id}/analyze` | Lead ID | Research and proposal workflow results |
| `POST /api/v1/emails/preview`, `PUT /api/v1/emails/approval`, `POST /api/v1/emails/send` | Lead and approval details | Preview, approve, then send an email |
| `GET /api/v1/emails`, `GET /api/v1/emails/{email_id}` | Optional filters or email ID | Email history and status |
| `GET /api/v1/calls`, `GET /api/v1/calls/{call_id}`, `POST /api/v1/calls/dispatch` | Optional history filters or validated dispatch request | Protected call history or authorized dispatch |
| `GET /api/v1/calling-eligibility/...` | Consent and eligibility inputs | Consent and call eligibility status |

Workflow lifecycle:

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/workflows` | Discover leads and create a workflow |
| `GET /api/v1/workflows` | Paginate workflow summaries |
| `GET /api/v1/workflows/{workflow_id}` | Read workflow state |
| `GET /api/v1/workflows/{workflow_id}/results` | Read generated research, retrieved context, and proposal |
| `POST /api/v1/workflows/{workflow_id}/select` | Select a lead and resume the agent pipeline |
| `POST /api/v1/workflows/{workflow_id}/approve` | Approve or reject the generated proposal |
| `POST /api/v1/workflows/{workflow_id}/outreach` | Explicitly authorize an approved email or voice action |

To prepare outreach, call research first, retrieve knowledge with a query you choose, then pass the lead and whichever results are relevant to proposal generation. If no documented business need exists, the proposal provides neutral, permission-based outreach rather than inventing a pain point.

The Competitors tab searches Google Places using the lead's category, address, and map coordinates, excludes the selected business, and only displays listings whose available category matches and coordinates fall within `LEADSUTRA_COMPETITOR_RADIUS_METERS` (10 km by default). It stores results in MongoDB. When no Places API key is configured it can use the existing Google Maps browser fallback; install Chromium with `python -m playwright install chromium`. If the lead lacks coordinates or no matching listings are found, the endpoint returns an explicit status instead of unverified results. Research summaries are constructed from recorded lead details and show verified facts, reasonable inferences, and missing information separately; generated claims are not used as evidence. Lead scoring responses include the evidence-based points by dimension and factor.

### 1. Lead Discovery

`POST /api/v1/leads/discover`

Example request:

```json
{
  "query": "digital marketing agency",
  "location": "Nashik",
  "limit": 10,
  "priority": "high"
}
```

The response and MongoDB lead records omit these fields:

- `discovery.sub_category`
- `discovery.source_ref`
- `enrichment.final_url`
- `enrichment.operating_hours`

The discovery section retains `source_url` and `website`. The enrichment section retains `website_url` and `website_status`.

The existing internal behavior remains unchanged:

- `sub_category` remains available as a scoring fallback.
- `source_ref` supports provenance and listing-contact fallback.
- Operating-hours evidence continues to contribute to scoring.
- Website validation, redirects, fetching, and website-based enrichment remain unchanged.
- The crawler uses resolved page URLs during validation and enrichment without storing a separate `final_url`.
- Older saved JSON runs are imported into MongoDB on access. Reserialization omits retired fields without rewriting historical files.

### 2. Email Outreach

| Step | Endpoint | Purpose |
|---|---|---|
| Preview | `POST /api/v1/emails/preview` | Generate a draft, recipient, subject, body, Message-ID, and SHA-256 `review_id` |
| Approve | `PUT /api/v1/emails/approval` | Approve a draft using `lead_id`, `review_id`, and `approved: true` |
| Send | `POST /api/v1/emails/send` | Queue a background send task and return HTTP `202` with `pending` status |
| Check result | `GET /api/v1/emails/{email_id}` | Retrieve the email result from MongoDB |

### 3. Stored Lead Search

`GET /api/v1/leads`

Requires a signed-in user session.

Searches stored MongoDB lead records without rerunning discovery, scraping, enrichment, or scoring.

**Query parameters**

| Parameter | Description |
|---|---|
| `q` | Case-insensitive substring search across business name, address, category, phone numbers, and website URLs |
| `category` | Trimmed, case-insensitive exact match |
| `qualification_status` | `Qualified`, `Needs Review`, `Not Qualified`, or `Unknown` |
| `priority` | `High`, `Medium`, `Low`, or `Unknown` |
| `limit` | Page size; default `25`, range `1–100` |
| `offset` | Pagination offset; default `0`, range `0–1,000,000` |

Search text and category are limited to 256 characters. Filters combine using AND logic, and `total` counts matching records before pagination.

**Response shape**

```json
{
  "items": [],
  "total": 0,
  "limit": 25,
  "offset": 0
}
```

The configured `LEAD_JSON_PATH` is used only to import legacy lead runs into MongoDB once. New runs are persisted to the `lead_runs` collection, while the newest canonical record per `lead_id` is indexed in `leads`.

An empty collection or no matches returns an empty page. MongoDB read failures are not silently replaced by local files.

**Implementation note:** MongoDB indexes support recent-record ordering and lead IDs. New snapshots do not depend on local filesystem paths.

### 4. Email History

`GET /api/v1/emails`

Requires a signed-in workspace session. No separate email admin token is used.

**Query parameters**

| Parameter | Description |
|---|---|
| `status` | Filter by `pending`, `sending`, `sent`, `failed`, or `uncertain` |
| `limit` | Page size; default `25`, range `1–100` |
| `offset` | Pagination offset; default `0`, range `0–1,000,000` |

Results are read from MongoDB's `email_results` collection and ordered by `created_at` descending, with `email_id` used to break ties.

**Response shape**

```json
{
  "emails": [],
  "total": 0,
  "limit": 25,
  "offset": 0
}
```

Each item reuses the existing email-result fields:

- `email_id`, `lead_id`, `review_id`
- `business_name`, `recipient`, `sender`
- `proposal_file`, `status`
- `created_at`, `sent_at`, `message_id`, `error`

Known workflow error codes remain visible. Other error details are replaced with `email_error_details_unavailable`.

> **Delivery semantics:** `sent` means the SMTP server accepted the message. It does not confirm delivery to the recipient's inbox. Queued, failed, and uncertain messages are not marked as delivered.

Retries update the existing review record, so history shows the current state rather than creating a separate record for each attempt. Existing email detail, approval, and sending endpoint contracts remain unchanged.

## 🔁 Email Retry & Observability

### Message Identification

- Generates RFC 2822 `Message-ID` values using Python's `email.utils.make_msgid()`.
- Persists the Message-ID upon SMTP acceptance.

### Structured Logging

The `leadsutra.email` and `leadsutra.smtp` loggers capture connection metadata and error tracebacks without exposing SMTP passwords or API tokens.

### Retry and Idempotency

| Current status | Behavior on another send request |
|---|---|
| `failed` / `uncertain` | Atomically reset to `pending` and queue another SMTP attempt |
| `sent` | Suppress duplicate sending |
| `pending` / `sending` | Suppress duplicate sending |

Retries preserve the original `email_id` and unique `review_id`.

## 🧪 Testing & Verification

Run commands from the `backend` directory.

**Full automated test suite**

```powershell
python -B -m unittest discover -s tests -v
```

**Module import verification**

```powershell
python -B -m tests.test_imports
```

**Email integration tests**

```powershell
python -B -m unittest tests.test_email_integration
```

> **Testing note:** Automated tests use mocked socket connections and mocked providers. They do not send real emails or make real network calls.

---

*LeadSutra AI Backend | API, data enrichment, qualification, scoring, voice, and email workflows.*
