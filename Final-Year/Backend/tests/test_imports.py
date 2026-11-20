"""Quick import test for the LeadSutra pipeline."""
import sys
import traceback

modules_to_test = [
    "app.agents.lead_pipeline.schema",
    "app.agents.lead_pipeline.scoring",
    "app.agents.lead_pipeline.pipeline",
    "app.agents.lead_pipeline.agent",
    "app.agents.research.agent",
    "app.agents.rag.agent",
    "app.agents.proposal.agent",
    "app.agents.research.prompt",
    "app.agents.research.schema",
    "app.agents.rag.schema",
    "app.agents.proposal.prompt",
    "app.agents.proposal.schema",
    "app.agents.orchestrator.schema",
    "app.agents.orchestrator.agent",
    "app.agents.email.schema",
    "app.agents.voice.schema",
    "app.agents.voice.prompt",
    "app.database.mongodb",
    "app.utils.safe_http",
    "app.integrations.maps_scraper",
    "app.integrations.google_places",
    "app.integrations.website_fetcher",
    "app.services.lead_results",
    "app.agents.email.agent",
    "app.integrations.smtp",
    "app.services.email_results",
    "app.services.email_service",
    "app.app",
]

errors = []
for module in modules_to_test:
    try:
        __import__(module)
        print(f"  OK  {module}")
    except Exception as exc:
        print(f" FAIL {module}: {exc}")
        traceback.print_exc()
        errors.append((module, exc))

print()
if errors:
    print(f"FAILED: {len(errors)} module(s) could not be imported")
    for mod, exc in errors:
        print(f"  - {mod}: {type(exc).__name__}: {exc}")
    sys.exit(1)
else:
    print("ALL IMPORTS OK")
