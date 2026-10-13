"""Validated JSON lead artifacts using the original per-run storage format."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from app.agents.lead_pipeline.schemas import LeadResult


_LEAD_RESULTS = TypeAdapter(list[LeadResult])
_CREDENTIAL_FIELDS = {
    "api_key", "apikey", "password", "secret", "secret_key", "access_token",
    "refresh_token", "client_secret", "private_key", "authorization", "credentials",
    "x_api_key", "x_goog_api_key",
}


def _ensure_no_credentials(value: object) -> None:
    """Reject credential fields or URL credentials rather than saving them."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.casefold().replace("-", "_") in _CREDENTIAL_FIELDS:
                raise ValueError("Lead results must not contain credential fields.")
            _ensure_no_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _ensure_no_credentials(item)
    elif isinstance(value, str):
        try:
            url = urlsplit(value)
        except ValueError:
            return
        if url.scheme.lower() in {"http", "https"} and url.netloc:
            if url.username is not None or any(
                key.casefold().replace("-", "_") in _CREDENTIAL_FIELDS
                for key, _ in parse_qsl(url.query)
            ):
                raise ValueError("Lead results must not contain URL credentials.")


class LeadResultStore:
    def __init__(self, root: str | Path | None = None):
        self.root = (
            Path(root) if root is not None
            else Path(__file__).resolve().parents[1] / "results" / "leads"
        ).resolve()

    def save(self, leads: list[LeadResult]) -> Path:
        """Validate every public record before publishing a complete run directory."""
        # Revalidate dumped models too: callers may have modified a nested value.
        validated = _LEAD_RESULTS.validate_python([
            lead.model_dump(mode="python", warnings=False) if isinstance(lead, LeadResult) else lead
            for lead in leads
        ])
        payload = _LEAD_RESULTS.dump_python(validated, mode="json")
        _ensure_no_credentials(payload)
        serialized = json.dumps(
            payload,
            ensure_ascii=False, indent=2, allow_nan=False,
        ) + "\n"
        run_dir = self.root / uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".run-", dir=self.root) as staging:
            staging_dir = Path(staging)
            with (staging_dir / "leads.json").open("w", encoding="utf-8", newline="\n") as artifact:
                artifact.write(serialized)
                artifact.flush()
                os.fsync(artifact.fileno())
            staging_dir.rename(run_dir)
        return run_dir / "leads.json"

    def load(self, run_id: str | UUID) -> list[LeadResult]:
        """Read a validated artifact by its generated run ID, never by a caller path."""
        path = self.root / UUID(str(run_id)).hex / "leads.json"
        return self._load_path(path)

    @staticmethod
    def _load_path(path: Path) -> list[LeadResult]:
        leads = _LEAD_RESULTS.validate_json(path.read_text(encoding="utf-8-sig"))
        _ensure_no_credentials(_LEAD_RESULTS.dump_python(leads, mode="json"))
        return leads

    def list_records(
        self, *, q: str | None = None, category: str | None = None,
        qualification_status: str | None = None, priority: str | None = None,
        limit: int = 25, offset: int = 0,
    ) -> tuple[list[LeadResult], int]:
        """Search saved canonical snapshots; newest run wins for each lead ID."""
        paths = [self.root] if self.root.is_file() else sorted(
            (path for path in self.root.glob("*/leads.json")
             if not path.parent.name.startswith(".")),
            key=lambda path: (path.stat().st_mtime_ns, str(path)), reverse=True,
        )
        by_id: dict[str, LeadResult] = {}
        for path in paths:
            for lead in self._load_path(path):
                by_id.setdefault(lead.lead_id, lead)
        query = (q or "").strip().casefold()
        matches: list[LeadResult] = []
        for lead in by_id.values():
            business, scoring = lead.discovery, lead.scoring
            if any(
                expected is not None and (actual or "").strip().casefold() != expected.strip().casefold()
                for actual, expected in (
                    (business.category, category), (scoring.priority, priority),
                    (scoring.qualification_status, qualification_status),
                )
            ):
                continue
            fields = [business.business_name, business.address, business.category,
                      business.phone, business.website, lead.enrichment.website_url,
                      *lead.enrichment.phone_numbers]
            if query and not any(query in (value or "").casefold() for value in fields):
                continue
            matches.append(lead)
        return matches[offset:offset + limit], len(matches)
