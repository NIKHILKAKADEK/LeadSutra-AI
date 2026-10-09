# LeadSutra AI Backend

Autonomous backend engine for **lead discovery, enrichment, qualification, scoring, voice calling, and email outreach**.

## 🚀 Quick Start

Run the following commands from the `backend` directory.

**Start the server**

```powershell
.\venv\Scripts\python.exe run.py
```

**API server:** http://127.0.0.1:8000

**Install or refresh dependencies**

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

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

## ⚙️ Environment Configuration

Configure environment variables in `backend/.env`. Use `.env.example` as the reference for supported settings.

| Setting | Default | Description |
|---|---|---|
| `LEADSUTRA_ENABLE_GOOGLE_PLACES` | `true` | Enable Google Places API discovery |
| `LEADSUTRA_ENABLE_MAPS_BROWSER` | `true` | Enable Playwright-based Maps scraping |
| `LEADSUTRA_ENABLE_MAPS_BROWSER_FALLBACK` | `false` | Use browser scraping after retryable Places API errors |
| `LEADSUTRA_MAPS_FALLBACK_ON_ZERO_RESULTS` | `false` | Use browser scraping when Places returns zero leads |
| `OUTBOUND_CALLS_ENABLED` | `true` | Enable live voice call dispatch |
| `EMAIL_SENDING_ENABLED` | `true` | Enable live SMTP email sending |

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
│   ├── lead_pipeline/    # Discovery, enrichment, scoring, qualification
│   ├── email/            # Email drafts and Message-ID construction
│   └── voice/            # Voice agent context and prompts
├── api/
│   ├── router.py         # Master API router
│   └── v1/               # Versioned API endpoints
├── core/
│   └── config.py         # Application settings
├── integrations/
│   ├── google_places.py  # Google Places API client
│   ├── maps_scraper.py   # Playwright Maps scraper
│   ├── website_fetcher.py# Website crawling and HTML parsing
│   ├── omnidimension.py  # Voice provider integration
│   └── smtp.py           # SMTP integration
├── schemas/              # Request and response models
├── services/             # Persistence and workflow orchestration
└── utils/                # Safe HTTP transport and DNS protection
```

## 🔍 API Overview

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

The response and newly saved `leads.json` records omit these fields:

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
- Older saved runs remain readable. Reserialization omits retired fields without rewriting historical files.

### 2. Email Outreach

| Step | Endpoint | Purpose |
|---|---|---|
| Preview | `POST /api/v1/emails/preview` | Generate a draft, recipient, subject, body, Message-ID, and SHA-256 `review_id` |
| Approve | `PUT /api/v1/emails/approval` | Approve a draft using `lead_id`, `review_id`, and `approved: true` |
| Send | `POST /api/v1/emails/send` | Queue a background send task and return HTTP `202` with `pending` status |
| Check result | `GET /api/v1/emails/{email_id}` | Retrieve the email result from SQLite |

### 3. Stored Lead Search

`GET /api/v1/leads`

Requires a reviewer or admin bearer token.

Searches stored lead artifacts without rerunning discovery, scraping, enrichment, or scoring.

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

The configured `LEAD_JSON_PATH` can reference a directory of published runs or a canonical JSON file. When multiple artifacts contain the same `lead_id`, the newest artifact by modification time takes precedence; ties are resolved by artifact path. Record order within a run is preserved.

Missing or empty storage and no matches return an empty page. Invalid or unreadable artifacts return HTTP `503` without exposing file contents.

**Implementation note:** Each request scans the saved JSON artifacts. There is no index or transactional snapshot across multiple run files.

### 4. Email History

`GET /api/v1/emails`

Requires the existing email admin bearer token.

**Query parameters**

| Parameter | Description |
|---|---|
| `status` | Filter by `pending`, `sending`, `sent`, `failed`, or `uncertain` |
| `limit` | Page size; default `25`, range `1–100` |
| `offset` | Pagination offset; default `0`, range `0–1,000,000` |

Results are read from the existing `email_results` SQLite table and ordered by `created_at` descending, with `email_id` used to break ties.

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
.\venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

**Module import verification**

```powershell
.\venv\Scripts\python.exe -B -m tests.test_imports
```

**Email integration tests**

```powershell
.\venv\Scripts\python.exe -B -m unittest tests/test_email_integration.py
```

> **Testing note:** Automated tests use mocked socket connections and mocked providers. They do not send real emails or make real network calls.

---

*LeadSutra AI Backend | API, data enrichment, qualification, scoring, voice, and email workflows.*
