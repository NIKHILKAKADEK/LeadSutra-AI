# LeadSutra AI Backend

Autonomous lead discovery, enrichment, qualification, scoring, voice calling, and email outreach backend engine.

---

## 🚀 Quick Start

Run commands from the `backend` directory using the virtual environment:

```powershell
.\venv\Scripts\python.exe run.py
```

The server listens locally on `http://127.0.0.1:8000`.

To install or refresh dependencies:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 🛠 Project Dependencies

| Package | Version | Purpose |
| --- | --- | --- |
| `fastapi` | `0.142.2` | High-performance ASGI Web API Framework |
| `uvicorn` | `0.54.0` | Production ASGI Server |
| `pydantic` | `2.13.5` | Data Validation & Schema Definition |
| `pydantic-settings` | `2.15.0` | Hierarchical Environment Settings Management |
| `httpx` | `0.28.1` | Async HTTP Client with Redirect & Pinned Transport Protection |
| `playwright` | `1.63.0` | Headless Browser Scraper for Google Maps & Dynamic Crawling |
| `beautifulsoup4` | `4.15.0` | HTML Parsing for Lead Web Scraping & Enrichment |
| `omnidimension` | `0.4.2` | Voice Calling Provider SDK |
| `python-dotenv` | `1.2.4` | Environment Variable Loading from `.env` |
| `requests` | `2.34.2` | HTTP Requests Library |

---

## ⚙️ Environment Configuration (`.env`)

Edit `backend/.env`. Key supported controls (see `.env.example` for details):

| Setting | Default | Description |
| --- | --- | --- |
| `LEADSUTRA_ENABLE_GOOGLE_PLACES` | `true` | Enable Google Places API for lead discovery |
| `LEADSUTRA_ENABLE_MAPS_BROWSER` | `true` | Enable Playwright Google Maps browser fallback scraper |
| `LEADSUTRA_ENABLE_MAPS_BROWSER_FALLBACK` | `false` | Fall back to Maps browser on Places retryable errors |
| `LEADSUTRA_MAPS_FALLBACK_ON_ZERO_RESULTS` | `false` | Fall back to Maps browser if Places returns zero leads |
| `OUTBOUND_CALLS_ENABLED` | `true` | Enable live voice call dispatching via OmniDimension API |
| `EMAIL_SENDING_ENABLED` | `true` | Enable live SMTP email outreach; previews remain available |

### Live SMTP Settings

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=leadsutraai.work@gmail.com
SMTP_PASSWORD=your_16_character_app_password
SMTP_FROM_ADDRESS=leadsutraai.work@gmail.com
SMTP_TIMEOUT_SECONDS=15
EMAIL_SENDING_ENABLED=true
```

> [!IMPORTANT]
> **Gmail Configuration**: Gmail SMTP requires a 16-character **Google App Password** generated under *Google Account Security → 2-Step Verification → App passwords*. Standard account passwords will be rejected with HTTP 535 authentication errors.

---

## 📦 Pipeline & System Architecture

```text
app/
├── agents/
│   ├── lead_pipeline/      # Discovery, Enrichment, Scoring & Qualification engine
│   ├── email/              # Email draft formatting & RFC 2822 Message-ID construction
│   └── voice/              # Outbound voice calling agent context & prompts
├── api/
│   ├── router.py           # Master API router
│   └── v1/                 # Endpoints: /leads, /calls, /calling-eligibility, /emails
├── core/
│   └── config.py           # Pydantic BaseSettings & EmailSettings configuration
├── integrations/
│   ├── google_places.py    # Google Places API client
│   ├── maps_scraper.py     # Playwright Google Maps browser scraper
│   ├── website_fetcher.py  # Async web crawler & HTML parser
│   ├── omnidimension.py    # OmniDimension Voice SDK integration
│   └── smtp.py             # Authenticated SMTP provider with TLS verification
├── schemas/                # Pydantic response & request validation models
├── services/               # Lead, Call, Proposal, and Email persistence & orchestration
└── utils/                  # Safe HTTP transport & DNS-rebinding protection
```

---

## 🔍 API Endpoints Overview

### 1. Lead Discovery (`POST /api/v1/leads/discover`)
```json
{
  "query": "digital marketing agency",
  "location": "Nashik",
  "limit": 10,
  "priority": "high"
}
```

The final response and newly saved `leads.json` records omit
`discovery.sub_category`, `discovery.source_ref`, `enrichment.final_url`, and
`enrichment.operating_hours`. Discovery still includes `source_url` and `website`;
enrichment still includes `website_url` and `website_status`. Website validation,
redirects, fetching, and website-based enrichment are unchanged.

Internal `sub_category` remains a scoring fallback, `source_ref` supports
provenance and listing-contact fallback, and operating-hours evidence still feeds
the existing score. Neither discovery provider scrapes `sub_category`. The crawler
uses resolved page URLs for validation and enrichment without storing a separate
`final_url`. Older saved runs remain readable; reserialization omits the retired
fields without rewriting historical files.

### 2. Email Outreach Flow
1. **Preview Draft (`POST /api/v1/emails/preview`)**:
   Generates draft subject, recipient, body, RFC 2822 `Message-ID`, and SHA256 `review_id`.
2. **Approve Draft (`PUT /api/v1/emails/approval`)**:
   Requires `lead_id`, `review_id`, and `approved: true`.
3. **Dispatch Email (`POST /api/v1/emails/send`)**:
   Queues background send task via `FastAPI BackgroundTasks`. Returns HTTP 202 `pending`.
4. **Check Result (`GET /api/v1/emails/{email_id}`)**:
   Retrieves SQLite result (`sent`, `pending`, `failed`, or `uncertain`).

### 3. Stored Lead Search (`GET /api/v1/leads`)

Requires a reviewer or admin bearer token. Reads the configured `LEAD_JSON_PATH`
(directory of published runs or a canonical JSON file) without invoking discovery,
scraping, enrichment, or scoring. The newest artifact by modification time wins
for each `lead_id`; ties use the artifact path, and records retain order within a run.

Parameters: `q` (case-insensitive substring in business name, address, category,
listing/enriched phones, and website URLs), `category` (trimmed, case-insensitive
exact match), `qualification_status` (`Qualified`, `Needs Review`, `Not Qualified`,
`Unknown`), `priority` (`High`, `Medium`, `Low`, `Unknown`), `limit` (default 25,
1-100), and `offset` (default 0, 0-1,000,000). Search text and category are limited
to 256 characters. Filters combine with AND; `total` counts matches before pagination.

Response: `{"items": [], "total": 0, "limit": 25, "offset": 0}`. Each item uses the
existing `lead_id`, `discovery`, `enrichment`, and `scoring` contract. Missing/empty
storage and no matches produce an empty page. Invalid or unreadable artifacts
return 503 without revealing file contents. Every request scans the saved JSON;
there is no index or transactional snapshot across multiple run files.

### 4. Email History (`GET /api/v1/emails`)

Requires the existing email admin bearer token. Parameters: `status` (`pending`,
`sending`, `sent`, `failed`, `uncertain`), `limit` (default 25, 1-100), and `offset`
(default 0, 0-1,000,000). Reads the existing `email_results` SQLite table, ordered
by `created_at` descending and `email_id` for ties. `total` counts matching rows.

Response: `{"emails": [], "total": 0, "limit": 25, "offset": 0}`. Items reuse the
email-result fields: `email_id`, `lead_id`, `review_id`, `business_name`, `recipient`,
`sender`, `proposal_file`, `status`, `created_at`, `sent_at`, `message_id`, and `error`.
Known workflow error codes remain visible; other error text becomes
`email_error_details_unavailable`. `sent` means SMTP acceptance, not confirmed
recipient delivery. Queued, failed, and uncertain records are never labeled delivered.
Existing email detail, approval, and sending endpoints retain their contracts.
Retries update the existing review record, so history shows current state rather
than a separate row per attempt.

---

## 🔁 Email Retry & Observability Architecture

- **RFC 2822 Message-ID**: Automatically generated via Python stdlib `email.utils.make_msgid()` before send and persisted upon SMTP acceptance.
- **Safe Structured Logging**: Loggers `leadsutra.email` and `leadsutra.smtp` log connection metadata and exact error tracebacks safely **without leaking SMTP passwords or API tokens**.
- **Idempotent Retry**:
  - **`failed` / `uncertain` records**: Calling `POST /api/v1/emails/send` atomically resets the record to `pending` and queues a new SMTP send attempt, preserving the original `email_id` and unique `review_id`.
  - **`sent` / `pending` / `sending` records**: Duplicate sends are suppressed to prevent accidental double-sending.

---

## 🧪 Testing & Verification

Run the full automated test suite:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Run explicit module import verification:

```powershell
.\venv\Scripts\python.exe -B -m tests.test_imports
```

Run email integration test suite:

```powershell
.\venv\Scripts\python.exe -B -m unittest tests/test_email_integration.py
```

> [!NOTE]
> All automated unit tests use mocked socket connections and mocked providers. **No real network calls or emails are sent during automated testing.**
