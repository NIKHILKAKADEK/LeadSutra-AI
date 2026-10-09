"""Regressions for empty results, shared schemas and bounded enrichment."""

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from app.agents.lead_pipeline.pipeline import LeadPipeline
from app.agents.lead_pipeline.scoring import score_lead
from app.app import app
from app.agents.lead_pipeline import schemas
from app.agents.lead_pipeline.pipeline import canonical_lead_output
from app.services.lead_results import LeadResultStore
from tests.test_lead_discovery import set_enrichment, business, crawled_website, pipeline


class PipelineDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_priority_band_is_explained_and_matches_persistence(self):
        service, *_ = pipeline([70, 65, 30])
        with TemporaryDirectory() as root:
            service.result_store = LeadResultStore(root)
            previous = getattr(app.state, "lead_discovery_service", None)
            app.state.lead_discovery_service = service
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test",
                ) as client:
                    for priority, expected_count in [("high", 0), ("mid", 2), ("low", 1)]:
                        before = set(Path(root).glob("*/leads.json"))
                        response = await client.post("/api/v1/leads/discover", json={
                            "query": "dentist", "location": "nashik", "limit": 3,
                            "priority": priority,
                        })
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["count"], expected_count)
                        artifact, = set(Path(root).glob("*/leads.json")) - before
                        self.assertEqual(response.json()["leads"], json.loads(artifact.read_text()))
                    before = set(Path(root).glob("*/leads.json"))
                    response = await client.post("/api/v1/leads/discover", json={
                        "query": "dentist", "location": "nashik", "limit": 3,
                        "qualification": "mixed",
                    })
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(before, set(Path(root).glob("*/leads.json")))
            finally:
                app.state.lead_discovery_service = previous

            result = await service.run("dentist", "nashik", 3, priority="high")
            self.assertEqual(result.diagnostics["candidates_discovered"], 3)
            self.assertEqual(result.diagnostics["priority_counts"], {"Medium": 2, "Low": 1})
            self.assertEqual(result.diagnostics["rejected_by_priority"], 3)
            self.assertEqual(result.diagnostics["rejected_by_qualification"], 0)
            self.assertTrue(all(value >= 0 for value in result.diagnostics["timings_seconds"].values()))

    async def test_parallel_real_stages_preserve_all_output_and_tie_order(self):
        records = [business(i, category="marketing agency", website="https://fixture.example/")
                   for i in range(6)]
        active = peak = 0
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def crawl(record):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append(record.lead_id)
            if active == 3:
                entered.set()
            try:
                await release.wait()
                # Complete different leads in different order.
                await asyncio.sleep((5 - int(record.lead_id[-3:])) * 0.001)
                return crawled_website(record)
            finally:
                active -= 1

        service, *_ = pipeline([70] * 6, records=records)
        crawler = SimpleNamespace(config=schemas.WebsiteCrawlerConfig(concurrency=3), crawl=crawl)
        set_enrichment(service, LeadPipeline(crawler=crawler))
        service.scorer = score_lead
        sequential_agent = LeadPipeline(crawler=SimpleNamespace(
            crawl=AsyncMock(side_effect=crawled_website),
        ))
        expected = []
        for record in records:
            lead = await sequential_agent._enrich(record)
            lead["lead_scoring"] = service.scorer(lead)
            expected.append(canonical_lead_output(lead).model_dump(mode="json"))
        expected.sort(key=lambda lead: lead["scoring"]["lead_score"], reverse=True)

        task = asyncio.create_task(service.run("agency", "Nashik", limit=6))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            self.assertEqual(len(calls), 3)
        finally:
            release.set()
        result = await asyncio.wait_for(task, timeout=2)
        actual = [canonical_lead_output(lead).model_dump(mode="json") for lead in result.leads]
        self.assertEqual(actual, expected)
        self.assertEqual(peak, 3)
        self.assertEqual(active, 0)
        self.assertCountEqual(calls, [record.lead_id for record in records])

    async def test_failed_enrichment_cancels_pending_work_without_saving(self):
        service, *_, scoring = pipeline([70] * 6)
        started = asyncio.Event()
        active = 0

        async def fail_or_wait(record):
            nonlocal active
            active += 1
            if active == 3:
                started.set()
            try:
                await started.wait()
                if record.lead_id == "lead_000":
                    raise RuntimeError("fixture stage failure")
                await asyncio.Event().wait()
            finally:
                active -= 1

        set_enrichment(service, SimpleNamespace(
            crawler=SimpleNamespace(config=schemas.WebsiteCrawlerConfig(concurrency=3)),
            enrich=fail_or_wait,
        ))
        with self.assertRaisesRegex(RuntimeError, "fixture stage failure"):
            await asyncio.wait_for(service.run("agency", "Nashik"), timeout=2)
        self.assertEqual(active, 0)
        service.result_store.save.assert_not_called()


class SharedSchemaTests(unittest.TestCase):
    def test_crawler_and_extractors_use_shared_models(self):
        from app.agents.lead_pipeline import pipeline as extractors
        from app.integrations import website_fetcher

        for module, names in [
            (website_fetcher, ["WebsitePage", "WebsiteCrawlResult", "WebsiteCrawlerConfig"]),
            (extractors, ["BusinessProfile", "ContactExtraction", "SocialMediaExtraction",
                          "TechnologyExtraction"]),
        ]:
            for name in names:
                self.assertIs(getattr(module, name), getattr(schemas, name))

    def test_pipeline_uses_single_scorer_and_keeps_public_contract(self):
        from app.agents.lead_pipeline import pipeline, scoring

        self.assertIs(pipeline.score_lead, scoring.score_lead)
        self.assertIs(pipeline.LeadPipeline().scorer.func, scoring.score_lead)
        self.assertEqual(schemas.ScoringData().model_dump(), {
            "lead_score": None, "priority": "Unknown", "qualification_status": "Unknown",
        })
