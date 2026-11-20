# LeadSutra AI

LeadSutra AI is a full-stack, AI-assisted lead generation and outreach workspace. It combines lead discovery and enrichment, a transparent 17-factor scoring model, LangGraph workflow orchestration, grounded business research, RAG retrieval, proposal generation, email drafting, follow-up management, and voice-call eligibility/dispatch.

The system is designed around human-in-the-loop decisions: lead selection, email approval, calling consent, and outreach authorization remain explicit checkpoints in the workflow.

> Lead discovery and outreach integrations must be used responsibly and in accordance with applicable privacy, consent, anti-spam, telemarketing, and data-protection requirements.

## Platform Overview

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, React Router, Axios, Recharts, Framer Motion |
| Backend | FastAPI, Pydantic, Uvicorn |
| Workflows | LangGraph multi-agent orchestration |
| AI and RAG | Ollama, Groq, LangChain, Chroma |
| Persistence | MongoDB; SQLite for selected legacy and operational records |
| Integrations | Google Places, Google Maps/browser discovery, website extraction, SMTP, OmniDimension |

## Key Capabilities

- **Lead discovery:** Search by business category and location, with Google Places and optional browser-based discovery.
- **Lead enrichment:** Inspect websites and extract business, contact, and enrichment evidence.
- **Lead qualification:** Score leads with normalized 17-factor evidence and separate priority and qualification bands.
- **LangGraph workflow:** Move from discovery and lead selection through research, RAG, proposal generation, approval, and outreach.
- **Business research:** Generate grounded research summaries for selected leads.
- **Knowledge retrieval:** Query indexed project knowledge through a Chroma-backed RAG service.
- **Proposal generation:** Create outreach-ready proposal content using configured local or cloud models.
- **Email outreach:** Preview, edit, approve, send, and inspect email drafts through authenticated SMTP workflows.
- **Follow-up management:** Track follow-up tasks and their completion state.
- **Voice outreach:** Record consent, verify calling eligibility, dispatch authorized calls, and view call history.
- **Analytics:** Review lead and workflow-oriented workspace metrics.
- **Secure sessions:** Authenticate with MongoDB-backed accounts and expiring JWT sessions stored in HttpOnly cookies.

## Architecture

```text
Browser / React UI
        |
        |  HTTP / HttpOnly session cookie
        v
FastAPI API
        |
        +-- Auth and authorization
        +-- Lead discovery and enrichment
        +-- LangGraph workflow orchestrator
        +-- Research and RAG agents
        +-- Proposal and email agents
        +-- Voice eligibility and dispatch
        |
        +-- MongoDB
        +-- Chroma vector index
        +-- Google Places / Maps
        +-- Ollama / Groq
        +-- SMTP / OmniDimension
```

### Project Structure

```text
LeadSutra AI/
├── Backend/
│   ├── app/
│   │   ├── agents/         Lead pipeline, research, RAG, proposal, email, voice
│   │   ├── api/v1/         Versioned FastAPI routes
│   │   ├── core/           Application settings
│   │   ├── database/       MongoDB connection and persistence
│   │   ├── integrations/   Places, Maps, website, SMTP, voice providers
│   │   ├── models/         Domain and lead models
│   │   ├── services/       Persistence and orchestration services
│   │   └── app.py          FastAPI application and lifespan
│   ├── data/rag/           RAG source documents
│   ├── tests/              Backend test suite
│   ├── nashik_50_eval/     Recorded evaluation snapshot and metadata
│   ├── .env.example
│   └── requirements.txt
├── Frontend/
│   ├── src/
│   │   ├── components/     Layout and reusable UI
│   │   ├── context/        Authentication state
│   │   ├── pages/          Landing, workspace, CRM, analytics, and settings
│   │   ├── services/       API clients
│   │   └── types/          Frontend contracts
│   ├── .env.example
│   └── package.json
└── README.md
```

## Prerequisites

- Windows 10/11 or another environment capable of running Python and Node.js
- Python 3.11 or newer
- Node.js 20 or newer
- npm
- MongoDB local installation or MongoDB Atlas
- Optional: Ollama for local research/email models
- Optional: Google Places credentials for Places discovery
- Optional: Groq credentials for configured cloud proposals/email
- Optional: SMTP credentials for live email
- Optional: OmniDimension credentials for voice dispatch

## Local Setup

### 1. Clone the repository

```powershell
git clone <repository-url>
cd Final-Year
```

### 2. Configure the backend

```powershell
cd Backend
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set at least these required values in `Backend/.env`:

```env
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=leadsutra
AUTH_JWT_SECRET=<at-least-32-random-characters>
```

MongoDB connectivity and a sufficiently long JWT secret are required at startup. Never commit `.env` or real credentials.

Common optional configuration:

| Variable | Purpose |
|---|---|
| `GOOGLE_PLACES_API_KEY` | Google Places discovery |
| `LLM_PROVIDER` | LLM routing strategy |
| `OLLAMA_MODEL` | Default local model |
| `OLLAMA_RESEARCH_MODEL` | Local research model |
| `GROQ_API_KEY` | Groq cloud model access |
| `GROQ_MODEL` | Cloud model name |
| `EMAIL_SENDING_ENABLED` | Enable live SMTP sending |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP delivery |
| `OUTBOUND_CALLS_ENABLED` | Enable live voice dispatch |
| `OMNIDIM_API_KEY` | OmniDimension voice access |
| `CORS_ALLOWED_ORIGINS` | Exact trusted frontend origins |

### 3. Start the backend

From `Backend/`:

```powershell
python run.py
```

- API: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Health: http://127.0.0.1:8000/health

The backend can serve a built frontend through `/ui` when static files are available in `Backend/app/static/`.

### 4. Configure and start the frontend

Open a second terminal:

```powershell
cd Frontend
npm ci
npm run dev
```

Frontend: http://localhost:5173

For local development, Vite proxies `/api` requests to `http://127.0.0.1:8000`. No frontend environment variable is required. In production, configure `VITE_API_BASE_URL` only for a trusted same-origin API or backend-for-frontend; never place provider keys or bearer tokens in `VITE_*` variables.

## Environment and Security Notes

- Use `AUTH_COOKIE_SECURE=true` behind HTTPS.
- Keep session cookies in HttpOnly cookies rather than browser storage.
- Calling-eligibility operations retain reviewer/admin token checks.
- Email sending remains disabled until `EMAIL_SENDING_ENABLED=true`, valid SMTP settings, and explicit draft approval are configured.
- Voice dispatch remains disabled until outbound calling is enabled and provider/identity requirements are satisfied.
- Browser discovery and live crawling may require network access and provider billing.
- Restrict MongoDB credentials and rotate secrets regularly.

## Main API Areas

| Area | Examples |
|---|---|
| Authentication | `/api/v1/auth/signup`, `/login`, `/me`, `/logout` |
| Lead discovery | `/api/v1/leads/discover`, `/api/v1/leads`, `/api/v1/leads/{lead_id}` |
| Analytics | `/api/v1/analytics/overview` |
| Research | `/api/v1/research/generate`, `/api/v1/research/{lead_id}` |
| RAG | `/api/v1/rag/retrieve` |
| Proposals | `/api/v1/proposals/generate` |
| Email | `/api/v1/emails/preview`, `/approval`, `/send`, `/history` |
| Follow-ups | `/api/v1/follow-ups` |
| Voice and consent | `/api/v1/calling-eligibility`, `/api/v1/calls` |
| Workflows | `/api/v1/workflows`, selection, approval, and explicit outreach actions |

For request and response schemas, use the generated OpenAPI documentation at `/docs`.

## Short Execution Flow

1. **Authenticate** through the React workspace.
2. **Discover leads** by category and location through Google Places or browser discovery.
3. **Enrich and score** each lead using website evidence and the scoring model.
4. **Review a lead**, run business research, and retrieve relevant RAG knowledge.
5. **Generate and approve** a proposal or outreach draft.
6. **Execute authorized outreach** through email or voice and track follow-ups.

## Testing

Run the backend suite from `Backend/`:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Run focused frontend checks from `Frontend/`:

```powershell
npm run typecheck
npm run build
```

## Troubleshooting

### Backend fails because MongoDB is unavailable

Confirm `MONGODB_URI` is reachable and `MONGODB_DATABASE` is set. MongoDB is mandatory; the API does not fall back to in-memory persistence.

### Backend fails because of authentication configuration

Set `AUTH_JWT_SECRET` to a unique random string of at least 32 characters, then restart the process.

### Frontend cannot reach the API

Start the backend on port `8000` and leave `VITE_API_BASE_URL` unset locally. Confirm Vite is running on `5173` and the `/api` proxy is active.

### Google Maps or Places discovery is unavailable

Verify the relevant switches in `Backend/.env` and configure `GOOGLE_PLACES_API_KEY` for the Places API. Browser discovery may additionally require a Playwright Chromium installation.

### Email or voice actions are blocked

Email sending requires SMTP settings and explicit approval. Voice dispatch requires outbound calling to be enabled, provider credentials, and applicable calling eligibility/authorization.

## License

Add the project's license terms here before public distribution.

## Responsible Use

LeadSutra AI is an operational support tool, not a substitute for legal review or human judgment. Before discovery or outreach, verify:

- Legal basis or legitimate interest for processing
- Local consent and do-not-call obligations
- Anti-spam and commercial-message requirements
- Accurate representation of the sending organization
- Contact preference and opt-out handling
- Evidence and factual support for generated claims
