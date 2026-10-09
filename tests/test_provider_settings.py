"""Provider switches and dotenv precedence; provider requests stay mocked."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.agents.lead_pipeline.pipeline import LeadPipeline
from app.agents.lead_pipeline.schemas import PlacesConfig
from app.core.config import DiscoverySettings
from app.integrations.google_places import PlacesApiError, PlacesConfigurationError
from tests.test_lead_discovery import business


class DiscoverySettingsTests(unittest.TestCase):
    def test_dotenv_loads_credentials_switches_and_timeouts(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text(
                "GOOGLE_PLACES_API_KEY=fixture-file-key\n"
                "LEADSUTRA_ENABLE_GOOGLE_PLACES=false\n"
                "LEADSUTRA_ENABLE_MAPS_BROWSER=true\n"
                "LEADSUTRA_PLACES_MAX_ATTEMPTS=3\n"
                "LEADSUTRA_PLACES_TIMEOUT_SECONDS=12\n"
                "LEADSUTRA_PLACES_RETRY_DELAY_SECONDS=0.5\n",
                encoding="utf-8",
            )
            settings = DiscoverySettings(_env_file=path)
            config = PlacesConfig.from_env(settings)
            self.assertEqual(config.api_key, "fixture-file-key")
            self.assertEqual((config.max_attempts, config.timeout_seconds, config.retry_delay_seconds),
                             (3, 12, 0.5))
            self.assertFalse(settings.leadsutra_enable_google_places)
            self.assertTrue(settings.leadsutra_enable_maps_browser)
            self.assertNotIn("fixture-file-key", repr(settings))
            self.assertNotIn("GOOGLE_PLACES_API_KEY", os.environ)
            with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "fixture-process-key",
                                         "LEADSUTRA_ENABLE_GOOGLE_PLACES": "true"}):
                settings = DiscoverySettings(_env_file=path)
                self.assertTrue(settings.leadsutra_enable_google_places)
                self.assertEqual(PlacesConfig.from_env(settings).api_key, "fixture-process-key")

    def test_legacy_maps_key_alias_is_retained(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = DiscoverySettings(_env_file=None, google_maps_api_key="fixture-legacy-key")
            self.assertEqual(PlacesConfig.from_env(settings).api_key, "fixture-legacy-key")

    def test_invalid_switch_or_limits_fail_validation(self):
        with patch.dict(os.environ, {}, clear=True):
            for values in [{"leadsutra_enable_google_places": "maybe"},
                           {"leadsutra_places_max_attempts": 0},
                           {"leadsutra_places_timeout_seconds": 0},
                           {"leadsutra_places_retry_delay_seconds": -1}]:
                with self.subTest(values=values), self.assertRaises(ValidationError):
                    DiscoverySettings(_env_file=None, **values)

    def test_discovery_does_not_validate_unrelated_smtp_settings(self):
        with patch.dict(os.environ, {"SMTP_PORT": "invalid"}, clear=True):
            self.assertTrue(DiscoverySettings(_env_file=None).leadsutra_enable_google_places)


class ProviderSwitchTests(unittest.IsolatedAsyncioTestCase):
    def make_pipeline(self, *, places_enabled=True, maps_enabled=True, fallback=False, zero=False):
        settings = DiscoverySettings(
            _env_file=None,
            leadsutra_enable_google_places=places_enabled,
            leadsutra_enable_maps_browser=maps_enabled,
            leadsutra_enable_maps_browser_fallback=fallback,
            leadsutra_maps_fallback_on_zero_results=zero,
        )
        places = SimpleNamespace(search=AsyncMock(return_value=[business(0)]), last_records=[])
        browser = SimpleNamespace(search=AsyncMock(return_value=[business(1)]))
        pipeline = LeadPipeline(places_client=places, browser_discovery=browser,
                                discovery_settings=settings)
        return pipeline, places, browser

    async def test_maps_only_skips_places_entirely(self):
        pipeline, places, browser = self.make_pipeline(places_enabled=False)
        leads = await pipeline._discover("dentist", "Nashik", 3)
        places.search.assert_not_awaited()
        browser.search.assert_awaited_once_with(query="dentist", location="Nashik", limit=3)
        self.assertEqual(leads[0].lead_id, business(1).lead_id)
        self.assertEqual(pipeline.diagnostics["fallback_reason"], "google_places_disabled")

    async def test_places_only_never_starts_disabled_browser(self):
        for failure in [PlacesConfigurationError("Missing Places API key"),
                        PlacesApiError("fixture outage", retryable=True)]:
            with self.subTest(failure=type(failure).__name__):
                pipeline, places, browser = self.make_pipeline(maps_enabled=False, fallback=True, zero=True)
                places.search.side_effect = failure
                with self.assertRaises(type(failure)):
                    await pipeline._discover("dentist", "Nashik", 3)
                browser.search.assert_not_awaited()
                self.assertFalse(pipeline.diagnostics["missing_key_fallback_enabled"])

    async def test_places_only_zero_results_remain_empty(self):
        pipeline, places, browser = self.make_pipeline(maps_enabled=False, fallback=True, zero=True)
        places.search.return_value = []
        self.assertEqual(await pipeline._discover("dentist", "Nashik", 3), [])
        browser.search.assert_not_awaited()

    async def test_both_disabled_fail_without_provider_requests(self):
        pipeline, places, browser = self.make_pipeline(places_enabled=False, maps_enabled=False)
        with self.assertRaisesRegex(PlacesConfigurationError, "All discovery providers are disabled"):
            await pipeline._discover("dentist", "Nashik", 3)
        places.search.assert_not_awaited()
        browser.search.assert_not_awaited()

    async def test_missing_key_fallback_remains_enabled_by_default(self):
        pipeline, places, browser = self.make_pipeline()
        places.search.side_effect = PlacesConfigurationError("Missing Places API key")
        self.assertEqual(len(await pipeline._discover("dentist", "Nashik", 3)), 1)
        browser.search.assert_awaited_once()
        self.assertEqual(pipeline.diagnostics["fallback_reason"], "missing_places_api_key")
