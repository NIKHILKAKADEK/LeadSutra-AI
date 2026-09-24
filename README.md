# LeadSutra AI – Google Places Search

This first phase implements only asynchronous Google Places Text Search for business discovery.

## Setup

Create `.env` from `.env.example` and set `GOOGLE_MAPS_API_KEY` to a valid Google Maps Platform key with the Places API (New) enabled.

Run unit tests without contacting Google:

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not integration" -v
```

Run the optional real integration test (one Google Places request only):

```powershell
.\.venv\Scripts\python.exe -m pytest -m integration -v
```
