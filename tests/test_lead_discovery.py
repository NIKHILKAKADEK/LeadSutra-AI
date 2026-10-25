"""Pipeline and API regressions using local fixtures; no live provider calls."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.agents.lead_pipeline.pipeline import LeadPipeline
from app.agents.lead_pipeline.scoring import score_lead
from app.agents.lead_pipeline.scoring import classify_score
from app.app import app
from app.integrations.google_places import PlacesApiError, PlacesConfigurationError
from app.integrations.website_fetcher import WebsiteCrawler
from app.agents.lead_pipeline.schemas import WebsiteCrawlerConfig
from app.agents.lead_pipeline.schemas import BusinessRecord, CanonicalLead
from app.agents.lead_pipeline.schemas import WebsiteCrawlResult, WebsitePage, WebsiteStatus
from app.agents.lead_pipeline.schemas import LeadDiscoveryRunResult
from app.agents.lead_pipeline.pipeline import canonical_lead_output


def business(index, **changes):
    values = {
        "lead_id": f"lead_{index:03d}",
        "business_name": f"Fixture Agency {index}",
        "place_id": f"place_{index}",
        "address": f"{index} Fixture Road, Nashik",
        "discovery_source": "google_places",
        "source_url": f"https://maps.google.com/?cid={index}",
    }
    values.update(changes)
    return BusinessRecord.model_validate(values)


def enriched(record):
    return {
        "lead_id": record.lead_id,
        "business": record.model_dump(mode="json"),
        "profile": {},
        "website_analysis": {"status": "not_found"},
        "contacts": {},
        "social_links": {},
    }


def crawled_website(record):
    """Stored website evidence for exercising the existing extractors locally."""
    pages = [
        WebsitePage(
            page_url="https://fixture.example/", page_type="home",
            meta_description="Fixture Agency helps local businesses with digital marketing.",
            main_text="Fixture Agency helps local businesses build their digital presence.\n"
                      "We serve local businesses.\nFounded in 2010 with a team of 20 employees.",
            technology_signals=["meta-generator:WordPress"],
            outgoing_links=[{"url": url, "text": record.business_name} for url in [
                "https://facebook.com/fixture", "https://instagram.com/fixture",
                "https://linkedin.com/company/fixture", "https://x.com/fixture",
            ]],
        ),
        WebsitePage(page_url="https://fixture.example/services", page_type="services",
                    main_text="Services\nWe provide SEO and Web Design."),
        WebsitePage(page_url="https://fixture.example/products", page_type="products",
                    main_text="Products\nProducts include Analytics Dashboard."),
        WebsitePage(
            page_url="https://fixture.example/contact", page_type="contact",
            main_text="Contact person: Fixture Person\nhello@fixture.example\n+91 98765 43210\n"
                      "Monday: 09:00 - 17:00\nSunday: closed",
            outgoing_links=[{"url": "mailto:hello@fixture.example"}, {"url": "tel:+919876543210"}],
        ),
    ]
    return WebsiteCrawlResult(
        lead_id=record.lead_id, website_status=WebsiteStatus.ACTIVE,
        website_url=record.website,
        website_content=pages, contact_page_url=pages[-1].page_url,
        pages_visited=[page.page_url for page in pages],
    )


def set_enrichment(service, enrichment):
    """Inject local crawl evidence into the single pipeline implementation."""
    service.crawler = getattr(enrichment, "crawler", SimpleNamespace())
    service._enrich = enrichment._enrich if isinstance(enrichment, LeadPipeline) else enrichment.enrich


def pipeline(scores, *, records=None, coverage=100):
    records = records if records is not None else [business(i) for i in range(len(scores))]
    score_by_id = {record.lead_id: score for record, score in zip(records, scores)}
    places = SimpleNamespace(search=AsyncMock(side_effect=lambda **kw: records[:kw["limit"]]), last_records=[])
    browser = SimpleNamespace(search=AsyncMock(return_value=records))
    enrichment = SimpleNamespace(enrich=AsyncMock(side_effect=enriched))

    def score(lead):
        value = score_by_id[lead["lead_id"]]
        priority, qualification = classify_score(value, coverage)
        return {"lead_score": value, "priority": priority, "qualification_status": qualification}

    scoring = SimpleNamespace(score=Mock(side_effect=score))
    service = LeadPipeline(
        places_client=places, browser_discovery=browser, scorer=scoring.score,
        result_store=SimpleNamespace(save=Mock(return_value=None)),
    )
    service.allow_browser_fallback = False
    service.fallback_on_zero_results = False
    set_enrichment(service, enrichment)
    return service, places, browser, enrichment, scoring


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_qualification_filters_use_existing_statuses(self):
        expected = {
            "mixed": [0, 1, 2, 3, 4],
            "qualified": [0, 1],
            "partially_qualified": [2, 4],
            "needs_review": [2, 4],
            "not_qualified": [3],
        }
        for qualification, indexes in expected.items():
            with self.subTest(qualification=qualification):
                service, *_ = pipeline([95, 70, 50, 20, None])
                result = await service.run("agency", "Nashik", qualification=qualification)
                self.assertEqual([lead["lead_id"] for lead in result.leads],
                                 [f"lead_{i:03d}" for i in indexes])

    async def test_priority_filters_use_existing_bands(self):
        for priority, indexes in {"high": [0], "mid": [1], "low": [2, 3, 4]}.items():
            with self.subTest(priority=priority):
                service, *_ = pipeline([95, 70, 50, 20, None])
                result = await service.run("agency", "Nashik", priority=priority)
                self.assertEqual([lead["lead_id"] for lead in result.leads],
                                 [f"lead_{i:03d}" for i in indexes])

    async def test_high_priority_does_not_imply_qualified(self):
        service, *_ = pipeline([95], coverage=20)
        result = await service.run("agency", "Nashik", priority="high")
        self.assertEqual(result.leads[0]["lead_scoring"]["qualification_status"], "Needs Review")

    async def test_limit_one_is_applied_after_candidate_scoring(self):
        service, places, _, enrichment, scoring = pipeline([0] * 20 + [95])
        result = await service.run("agency", "Nashik", limit=1)
        self.assertEqual(result.leads[0]["lead_id"], "lead_020")
        self.assertEqual(places.search.call_args.kwargs["limit"], 21)
        self.assertEqual(enrichment.enrich.await_count, 21)
        self.assertEqual(scoring.score.call_count, 21)

    async def test_limit_ten_is_applied_after_priority_filter_and_sort(self):
        service, places, _, enrichment, _ = pipeline([0] * 30 + list(range(80, 100)))
        result = await service.run("agency", "Nashik", limit=10, priority="high")
        self.assertEqual([lead["lead_id"] for lead in result.leads],
                         [f"lead_{i:03d}" for i in range(49, 39, -1)])
        self.assertEqual(places.search.call_args.kwargs["limit"], 50)
        self.assertEqual(enrichment.enrich.await_count, 50)
        self.assertEqual(result.diagnostics["matching_candidates"], 20)

    async def test_candidate_pool_respects_existing_provider_cap(self):
        service, places, *_ = pipeline(list(range(60)))
        result = await service.run("agency", "Nashik", limit=60)
        self.assertEqual(places.search.call_args.kwargs["limit"], 60)
        self.assertEqual(len(result.leads), 60)

    async def test_missing_scores_sort_last_and_ties_keep_discovery_order(self):
        service, *_ = pipeline([None, 0, 70, 70])
        result = await service.run("agency", "Nashik")
        self.assertEqual([lead["lead_id"] for lead in result.leads],
                         ["lead_002", "lead_003", "lead_001", "lead_000"])

    async def test_fewer_matching_leads_are_not_fabricated(self):
        service, *_ = pipeline([95, 20])
        result = await service.run("agency", "Nashik", limit=10, priority="high")
        self.assertEqual(len(result.leads), 1)

    async def test_no_results_does_not_enrich_score_or_force_fallback(self):
        service, _, browser, enrichment, scoring = pipeline([])
        result = await service.run("agency", "Nashik")
        self.assertEqual(result.leads, [])
        self.assertFalse(result.fallback_used)
        browser.search.assert_not_awaited()
        enrichment.enrich.assert_not_awaited()
        scoring.score.assert_not_called()

    async def test_original_duplicate_keys_are_applied_before_enrichment(self):
        first = business(0)
        same_place = business(1, place_id=first.place_id)
        same_name_address = business(2, business_name="  FIXTURE   AGENCY 0 ", address=first.address)
        distinct = business(3)
        service, _, _, enrichment, _ = pipeline([80, 90, 95, 70],
                                                records=[first, same_place, same_name_address, distinct])
        result = await service.run("agency", "Nashik")
        self.assertEqual([lead["lead_id"] for lead in result.leads], [first.lead_id, distinct.lead_id])
        self.assertEqual(enrichment.enrich.await_count, 2)

    async def test_missing_phone_and_website_use_real_enrichment_and_scoring(self):
        record = business(0, phone=None, website=None)
        service, *_ = pipeline([None], records=[record])
        crawler = SimpleNamespace(crawl=AsyncMock(return_value=WebsiteCrawlResult(
            lead_id=record.lead_id, website_status=WebsiteStatus.NOT_FOUND
        )))
        set_enrichment(service, LeadPipeline(crawler=crawler))
        service.scorer = score_lead
        expected_input = await service._enrich(record)
        expected_score = service.scorer(expected_input)
        result = await service.run("agency", "Nashik")
        lead = canonical_lead_output(result.leads[0]).model_dump(mode="json")
        self.assertIsNone(lead["discovery"]["phone"])
        self.assertIsNone(lead["discovery"]["website"])
        self.assertEqual(lead["enrichment"]["website_status"], "not_found")
        self.assertEqual(lead["enrichment"]["phone_numbers"], [])
        self.assertEqual(lead["scoring"], expected_score)

    async def test_basic_mode_still_skips_enrichment_and_scoring(self):
        service, places, _, enrichment, scoring = pipeline([95, 20])
        result = await service.run("agency", "Nashik", limit=1, mode="basic")
        self.assertEqual(len(result.leads), 1)
        self.assertEqual(places.search.call_args.kwargs["limit"], 1)
        enrichment.enrich.assert_not_awaited()
        scoring.score.assert_not_called()

    async def test_invalid_filters_or_limit_fail_before_provider_calls(self):
        for changes in [{"limit": 0}, {"priority": "medium"}, {"qualification": "invalid"},
                        {"mode": "basic", "priority": "high"}]:
            with self.subTest(changes=changes):
                service, places, *_ = pipeline([95])
                with self.assertRaises(ValueError):
                    await service.run("agency", "Nashik", **changes)
                places.search.assert_not_awaited()

    async def test_scoring_errors_still_propagate(self):
        service, *_, scoring = pipeline([95])
        scoring.score.side_effect = RuntimeError("fixture scoring failure")
        with self.assertRaisesRegex(RuntimeError, "fixture scoring failure"):
            await service.run("agency", "Nashik")


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_keeps_automatic_browser_fallback(self):
        service, places, browser, *_ = pipeline([95])
        places.search.side_effect = PlacesConfigurationError("Missing Places API key")
        result = await service.run("agency", "Nashik", priority="high")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.source, "google_maps_browser")
        self.assertEqual(result.fallback_reason, "missing_places_api_key")
        browser.search.assert_awaited_once()
        lead = canonical_lead_output(result.leads[0]).model_dump(mode="json")
        self.assertNotIn("fallback_used", lead["discovery"])
        self.assertNotIn("discovery_source", lead["discovery"])
        self.assertTrue(result.leads[0]["business"]["fallback_used"])

    async def test_retryable_api_failure_uses_enabled_fallback(self):
        service, places, browser, *_ = pipeline([95])
        service.allow_browser_fallback = True
        places.search.side_effect = PlacesApiError("fixture outage", retryable=True, status_code=503)
        result = await service.run("agency", "Nashik")
        self.assertEqual(result.fallback_reason, "transient_api_failure:503")
        browser.search.assert_awaited_once()

    async def test_failure_gates_are_preserved(self):
        for error, enabled in [
            (PlacesApiError("fixture outage", retryable=True), False),
            (PlacesApiError("fixture rejection", retryable=False), True),
            (PlacesConfigurationError("fixture rejected credentials"), True),
        ]:
            with self.subTest(error=error, enabled=enabled):
                service, places, browser, *_ = pipeline([95])
                service.allow_browser_fallback = enabled
                places.search.side_effect = error
                with self.assertRaises(type(error)):
                    await service.run("agency", "Nashik")
                browser.search.assert_not_awaited()

    async def test_zero_results_require_both_existing_flags(self):
        for enabled, zero_flag in [(False, False), (True, False), (False, True), (True, True)]:
            with self.subTest(enabled=enabled, zero_flag=zero_flag):
                service, places, browser, *_ = pipeline([95])
                places.search.side_effect = None
                places.search.return_value = []
                service.allow_browser_fallback = enabled
                service.fallback_on_zero_results = zero_flag
                result = await service.run("agency", "Nashik")
                self.assertEqual(result.fallback_used, enabled and zero_flag)
                self.assertEqual(browser.search.await_count, int(enabled and zero_flag))

    async def test_partial_places_results_are_preserved_without_browser(self):
        service, places, browser, *_ = pipeline([95])
        service.allow_browser_fallback = True
        places.last_records = [business(0)]
        places.search.side_effect = PlacesApiError("fixture page failure", retryable=True)
        result = await service.run("agency", "Nashik")
        self.assertEqual(len(result.leads), 1)
        self.assertFalse(result.fallback_used)
        self.assertTrue(result.diagnostics["partial_results_preserved"])
        browser.search.assert_not_awaited()


class OutputTests(unittest.TestCase):
    def test_maps_evidence_facts_and_preserves_discovery_fields(self):
        lead = enriched(business(0, primary_type="marketing_agency", review_count=12,
                                 email="fixture@example.org", source_ref="places/place_0",
                                 source_attributions=[{"displayName": "Fixture attribution"}]))
        lead["profile"] = {
            "business_description": {"value": "Existing business description", "source_urls": ["internal-only"]},
            "about_info": [{"value": "First fact", "source_urls": ["internal-only"]},
                           {"value": "Second fact", "source_urls": ["internal-only"]}],
            "services": [{"value": "SEO", "source_urls": ["internal-only"]}],
            "products": [{"value": "Analytics", "source_urls": ["internal-only"]}],
            "target_customers": [{"value": "Retail", "source_urls": ["internal-only"]}],
            "operating_hours": [{"day": "Monday", "opens": "09:00", "closes": "17:00",
                                 "closed": False, "source_url": "internal-only"}],
        }
        lead["website_analysis"] = {
            "status": "active", "website_content": [{"main_text": "internal-only"}],
            "website_url": "http://fixture.example", "final_url": "https://fixture.example/",
            "technology_stack": [{"name": "WordPress", "evidence": ["internal-only"]}],
        }
        lead["contacts"] = {
            "contact_person": {"value": "Fixture Person", "source_urls": ["internal-only"]},
            "emails": [{"email": "fixture@example.org", "source_urls": ["internal-only"]}],
            "phone_numbers": [{"value": "98765 43210", "normalized": "9876543210",
                               "source_urls": ["internal-only"]}],
            "contact_page_url": "https://fixture.example/contact",
        }
        lead["social_links"] = {
            "facebook": {"url": "https://facebook.com/fixture", "source_url": "internal-only"},
            "twitter": {"url": "https://x.com/fixture", "source_url": "internal-only"},
        }
        lead["lead_scoring"] = {"lead_score": 95, "priority": "High",
                                "qualification_status": "Qualified", "score_breakdown": {"internal-only": 1}}
        original = copy.deepcopy(lead)
        output = canonical_lead_output(lead).model_dump(mode="json")
        self.assertEqual(set(output), {"lead_id", "discovery", "enrichment", "scoring"})
        self.assertNotIn("lead_id", output["discovery"])
        internal_fields = {"lead_id", "place_id", "primary_type", "discovery_source",
                           "fallback_used", "fallback_reason", "source_attributions",
                           "sub_category", "source_ref"}
        self.assertEqual(output["discovery"], {k: v for k, v in lead["business"].items()
                                              if k not in internal_fields})
        self.assertEqual(output["enrichment"]["about"], "First fact Second fact")
        self.assertEqual(output["enrichment"]["business_description"], "Existing business description")
        self.assertEqual(output["enrichment"]["website_url"], "http://fixture.example")
        self.assertNotIn("final_url", output["enrichment"])
        self.assertEqual(output["enrichment"]["social_links"]["twitter"], "https://x.com/fixture")
        self.assertNotIn("operating_hours", output["enrichment"])
        self.assertEqual(output["enrichment"]["services"], ["SEO"])
        self.assertEqual(output["enrichment"]["products"], ["Analytics"])
        self.assertEqual(output["enrichment"]["target_customers"], ["Retail"])
        self.assertEqual(output["enrichment"]["emails"], ["fixture@example.org"])
        self.assertEqual(output["enrichment"]["phone_numbers"], ["9876543210"])
        self.assertEqual(output["enrichment"]["contact_person"], "Fixture Person")
        self.assertEqual(output["enrichment"]["technology_stack"], ["WordPress"])
        self.assertEqual(output["enrichment"]["contact_page_url"], "https://fixture.example/contact")
        self.assertNotIn("internal-only", json.dumps(output))
        self.assertEqual(lead, original)
        self.assertEqual(CanonicalLead.model_validate(output).model_dump(mode="json"), output)

    def test_missing_data_keeps_null_empty_and_unknown_conventions(self):
        output = canonical_lead_output(enriched(business(0))).model_dump(mode="json")
        self.assertIsNone(output["discovery"]["phone"])
        self.assertIsNone(output["discovery"]["website"])
        self.assertIsNone(output["discovery"]["rating"])
        self.assertEqual(output["enrichment"]["about"], "")
        for field in ["website_url", "business_description"]:
            self.assertIsNone(output["enrichment"][field])
        self.assertNotIn("operating_hours", output["enrichment"])
        self.assertNotIn("final_url", output["enrichment"])
        self.assertEqual(output["enrichment"]["social_links"],
                         {"facebook": None, "instagram": None, "linkedin": None, "twitter": None})
        self.assertEqual(output["scoring"],
                         {"lead_score": None, "priority": "Unknown", "qualification_status": "Unknown"})

    def test_existing_plain_hours_are_omitted_and_website_about_is_mapped(self):
        lead = enriched(business(0))
        lead["profile"]["operating_hours"] = {"Sunday": {"closed": True}}
        lead["website_analysis"]["about"] = [{"text": "Existing website about text"}]
        output = canonical_lead_output(lead).model_dump(mode="json")
        self.assertEqual(output["enrichment"]["about"], "Existing website about text")
        self.assertNotIn("operating_hours", output["enrichment"])


class CrawlerOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirected_pages_still_supply_enrichment_and_contacts(self):
        requested = []

        def respond(request):
            requested.append(str(request.url))
            if request.url.scheme == "http":
                return httpx.Response(301, headers={"location": "https://fixture.example/"})
            if request.url.path == "/":
                return httpx.Response(200, headers={"content-type": "text/html"}, text=
                    '<main><p>Fixture Agency provides services to local businesses.</p>'
                    '<a href="/contact">Contact</a></main>')
            return httpx.Response(200, headers={"content-type": "text/html"}, text=
                '<main><p>Monday: 09:00 - 17:00</p><p>hello@fixture.example</p>'
                '<a href="tel:+919876543210">Call</a></main>')

        record = business(0, website="http://fixture.example")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            crawler = WebsiteCrawler(client=client, config=WebsiteCrawlerConfig(max_pages=2))
            raw = await LeadPipeline(crawler=crawler)._enrich(record)
        self.assertEqual(requested, ["http://fixture.example/", "https://fixture.example/",
                                     "https://fixture.example/contact"])
        self.assertNotIn("final_url", raw["website_analysis"])
        self.assertEqual(raw["website_analysis"]["website_content"][0]["page_url"],
                         "https://fixture.example/")
        self.assertEqual(raw["profile"]["operating_hours"][0]["day"], "Monday")
        output = canonical_lead_output(raw).model_dump(mode="json")
        self.assertEqual(output["enrichment"]["website_url"], "http://fixture.example/")
        self.assertEqual(output["enrichment"]["website_status"], "active")
        self.assertEqual(output["enrichment"]["contact_page_url"], "https://fixture.example/contact")
        self.assertEqual(output["enrichment"]["emails"], ["hello@fixture.example"])
        self.assertEqual(output["enrichment"]["phone_numbers"], ["+919876543210"])
        self.assertFalse({"final_url", "operating_hours"} & output["enrichment"].keys())

    async def test_rendering_uses_resolved_url_without_storing_final_url(self):
        manager = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        def respond(request):
            if request.url.scheme == "http":
                return httpx.Response(302, headers={"location": "https://fixture.example/"})
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  text='<script src="app.js"></script>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            crawler = WebsiteCrawler(client=client, browser_manager_factory=lambda config: manager)
            crawler._render_page = AsyncMock(return_value=
                '<main><p>Fixture Agency helps local businesses.</p></main>')
            result = await crawler.crawl(business(0, website="http://fixture.example"))
        crawler._render_page.assert_awaited_once_with("https://fixture.example/", manager)
        manager.close.assert_awaited_once()
        self.assertEqual(result.website_status, WebsiteStatus.ACTIVE)
        self.assertNotIn("final_url", result.model_dump())

    async def test_external_redirects_remain_blocked(self):
        requested = []
        def respond(request):
            requested.append(str(request.url))
            return httpx.Response(302, headers={"location": "https://outside.example/"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            crawler = WebsiteCrawler(client=client)
            result = await crawler.crawl(business(0, website="http://fixture.example"))
        self.assertEqual(requested, ["http://fixture.example/"])
        self.assertEqual(result.website_status, WebsiteStatus.UNREACHABLE)
        self.assertEqual(result.website_content, [])
        self.assertIn("Blocked redirect outside", result.crawl_errors[0].message)
        self.assertNotIn("final_url", result.model_dump())


class EnrichmentScoringTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_provenance_contacts_and_category_scoring_are_preserved(self):
        record = business(0, category=None, sub_category="Dentist", source_url=None,
                          source_ref="places/place_0", website=None,
                          phone="+91 98765 43210", email="hello@fixture.example",
                          description="Verified listing description")
        crawler = SimpleNamespace(crawl=AsyncMock(return_value=WebsiteCrawlResult(
            lead_id=record.lead_id, website_status=WebsiteStatus.NOT_FOUND,
        )))
        raw = await LeadPipeline(crawler=crawler)._enrich(record)
        self.assertEqual(raw["profile"]["business_description"]["source_urls"], [record.source_ref])
        self.assertEqual(raw["contacts"]["emails"][0]["source_urls"], [record.source_ref])
        self.assertEqual(raw["contacts"]["phone_numbers"][0]["source_urls"], [record.source_ref])
        expected = copy.deepcopy(raw)
        expected["business"]["category"] = record.sub_category
        expected["business"]["sub_category"] = None
        self.assertEqual(score_lead(raw), score_lead(expected))
        output = canonical_lead_output(raw).model_dump(mode="json")
        self.assertFalse({"sub_category", "source_ref"} & output["discovery"].keys())
        self.assertIsNone(output["discovery"]["source_url"])
        self.assertEqual(output["enrichment"]["emails"], ["hello@fixture.example"])
        self.assertEqual(output["enrichment"]["phone_numbers"], ["+919876543210"])

    async def test_hours_remain_internal_scoring_evidence(self):
        record = business(0, website="http://fixture.example", rating=4.8, review_count=120)
        crawler = SimpleNamespace(crawl=AsyncMock(side_effect=crawled_website))
        raw = await LeadPipeline(crawler=crawler)._enrich(record)
        self.assertEqual(raw["profile"]["operating_hours"][0]["day"], "Monday")
        self.assertEqual(score_lead(raw), {
            "lead_score": 86.7, "priority": "High", "qualification_status": "Qualified",
        })
        without_hours = copy.deepcopy(raw)
        without_hours["profile"]["operating_hours"] = []
        self.assertLess(score_lead(without_hours)["lead_score"], score_lead(raw)["lead_score"])
        self.assertNotIn("operating_hours", canonical_lead_output(raw).enrichment.model_dump())

    async def test_real_pipeline_enriches_and_scores_each_candidate_once(self):
        records = [business(i, website="http://fixture.example", rating=4.8, review_count=120)
                   for i in range(3)]
        service, _, browser, *_ = pipeline([None] * len(records), records=records)
        crawler = SimpleNamespace(crawl=AsyncMock(side_effect=crawled_website))
        enrichment = LeadPipeline(crawler=crawler)
        scoring = SimpleNamespace(score=score_lead)
        # Compare with the same existing algorithms before tracking the pipeline calls.
        expected = {}
        for record in records:
            data = await enrichment._enrich(record)
            expected[record.lead_id] = scoring.score(data)
        crawler.crawl.reset_mock()
        enrichment._enrich = AsyncMock(wraps=enrichment._enrich)
        scoring.score = Mock(wraps=scoring.score)
        stages = Mock()
        stages.attach_mock(enrichment._enrich, "enrich")
        stages.attach_mock(scoring.score, "score")
        set_enrichment(service, enrichment)
        service.scorer = scoring.score

        result = await service.run("agency", "Nashik", qualification="qualified", priority="high")
        original = copy.deepcopy(result.leads)
        outputs = [canonical_lead_output(lead).model_dump(mode="json") for lead in result.leads]
        self.assertEqual(len(outputs), len(records))
        self.assertEqual(enrichment._enrich.await_count, len(records))
        self.assertEqual(crawler.crawl.await_count, len(records))
        self.assertEqual(scoring.score.call_count, len(records))
        self.assertEqual([call[0] for call in stages.mock_calls], ["enrich", "score"] * len(records))
        browser.search.assert_not_awaited()
        self.assertEqual(result.leads, original)
        for output in outputs:
            with self.subTest(lead_id=output["lead_id"]):
                self.assertEqual(set(output), {"lead_id", "discovery", "enrichment", "scoring"})
                self.assertEqual(output["scoring"], expected[output["lead_id"]])
                self.assertEqual(CanonicalLead.model_validate(output).model_dump(mode="json"), output)
                facts = output["enrichment"]
                self.assertEqual(facts["website_status"], "active")
                self.assertEqual(facts["website_url"], "http://fixture.example")
                self.assertNotIn("final_url", facts)
                self.assertEqual(facts["business_description"], crawled_website(records[0]).website_content[0].meta_description)
                self.assertEqual(facts["services"], ["SEO", "Web Design"])
                self.assertEqual(facts["products"], ["Analytics Dashboard"])
                self.assertEqual(facts["target_customers"], ["local businesses"])
                self.assertEqual(facts["contact_person"], "Fixture Person")
                self.assertEqual(facts["emails"], ["hello@fixture.example"])
                self.assertEqual(facts["phone_numbers"], ["+919876543210"])
                self.assertEqual(facts["technology_stack"], ["WordPress"])
                self.assertEqual(facts["contact_page_url"], "https://fixture.example/contact")
                self.assertEqual(facts["social_links"]["twitter"], "https://x.com/fixture")
                self.assertNotIn("operating_hours", facts)

    async def test_real_enrichment_and_scoring_through_discovery_api(self):
        record = business(0, website="http://fixture.example", rating=4.8, review_count=120)
        service, *_ = pipeline([None], records=[record])
        crawler = SimpleNamespace(crawl=AsyncMock(side_effect=crawled_website))
        set_enrichment(service, LeadPipeline(crawler=crawler))
        service.scorer = score_lead
        data = await service._enrich(record)
        data["lead_scoring"] = service.scorer(data)
        expected = canonical_lead_output(data).model_dump(mode="json")
        crawler.crawl.reset_mock()
        service.scorer = Mock(wraps=service.scorer)
        with patch.object(app.state, "lead_discovery_service", service, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/leads/discover", json={
                    "query": "agency", "location": "Nashik", "limit": 1, "priority": "high",
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["leads"], [expected])
        crawler.crawl.assert_awaited_once()
        service.scorer.assert_called_once()

    async def test_partial_extraction_keeps_other_facts_and_existing_score(self):
        record = business(0, website="http://fixture.example")
        service, *_ = pipeline([None], records=[record])
        set_enrichment(service, LeadPipeline(
            crawler=SimpleNamespace(crawl=AsyncMock(side_effect=crawled_website))
        ))
        service.scorer = score_lead
        with patch("app.agents.lead_pipeline.pipeline.extract_contacts", side_effect=RuntimeError("fixture failure")):
            result = await service.run("agency", "Nashik")
        raw = result.leads[0]
        output = canonical_lead_output(raw).model_dump(mode="json")
        self.assertEqual(raw["extraction_metadata"]["module_status"]["contacts"], "not_available")
        self.assertEqual(raw["extraction_metadata"]["overall_status"], "partial")
        self.assertEqual(output["enrichment"]["services"], ["SEO", "Web Design"])
        self.assertEqual(output["enrichment"]["technology_stack"], ["WordPress"])
        self.assertEqual(output["enrichment"]["social_links"]["twitter"], "https://x.com/fixture")
        self.assertIsNone(output["enrichment"]["contact_person"])
        self.assertEqual(output["enrichment"]["emails"], [])
        self.assertEqual(output["enrichment"]["phone_numbers"], [])
        self.assertEqual(output["scoring"], score_lead(raw))

    async def test_crawler_failure_preserves_listing_contact_and_null_conventions(self):
        record = business(0, website="http://fixture.example", phone="+91 98765 43210")
        service, *_ = pipeline([None], records=[record])
        set_enrichment(service, LeadPipeline(
            crawler=SimpleNamespace(crawl=AsyncMock(side_effect=RuntimeError("fixture crawl failure")))
        ))
        service.scorer = score_lead
        result = await service.run("agency", "Nashik")
        raw = result.leads[0]
        output = canonical_lead_output(raw).model_dump(mode="json")
        self.assertEqual(output["enrichment"]["website_status"], "uncertain")
        self.assertEqual(output["enrichment"]["website_url"], record.website)
        self.assertNotIn("final_url", output["enrichment"])
        self.assertIsNone(output["enrichment"]["business_description"])
        self.assertEqual(output["enrichment"]["about"], "")
        self.assertEqual(output["enrichment"]["phone_numbers"], ["+919876543210"])
        self.assertTrue(raw["website_analysis"]["crawl_errors"])
        self.assertNotIn("fixture crawl failure", json.dumps(output))
        self.assertEqual(output["scoring"], score_lead(raw))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service, self.places, _, _, _ = pipeline([95, 70, 50, 20, None])
        self.factory = patch("app.app.LeadPipeline", return_value=self.service)
        self.factory.start()
        self.lifespan = app.router.lifespan_context(app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.request = {"query": "agency", "location": "Nashik", "limit": 10, "priority": "low"}

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.factory.stop()

    async def test_priority_only_api_contract(self):
        for priority, label in [("high", "High"), ("mid", "Medium"), ("low", "Low")]:
            with self.subTest(priority=priority):
                response = await self.client.post("/api/v1/leads/discover", json=self.request | {"priority": priority})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["count"], len(body["leads"]))
                self.assertTrue(body["leads"])
                self.assertTrue(all(lead["scoring"]["priority"] == label for lead in body["leads"]))
                self.assertEqual(set(body["leads"][0]), {"lead_id", "discovery", "enrichment", "scoring"})

    async def test_priority_is_required(self):
        request = {key: value for key, value in self.request.items() if key != "priority"}
        response = await self.client.post("/api/v1/leads/discover", json=request)
        self.assertEqual(response.status_code, 422)
        self.places.search.assert_not_awaited()

    async def test_limits_one_and_ten_through_api(self):
        service, *_ = pipeline([0] * 20 + [99] + [80] * 29)
        app.state.lead_discovery_service = service
        for limit in [1, 10]:
            with self.subTest(limit=limit):
                response = await self.client.post("/api/v1/leads/discover", json=self.request | {"limit": limit, "priority": "high"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], limit)
                self.assertEqual(response.json()["leads"][0]["lead_id"], "lead_020")

    async def test_input_validation_and_whitespace(self):
        for changes in [{"priority": "medium"}, {"priority": "mixed"}, {"priority": None},
                        {"qualification": "qualified"}, {"limit": 0}, {"limit": 61},
                        {"query": ""}, {"location": ""}]:
            with self.subTest(changes=changes):
                response = await self.client.post("/api/v1/leads/discover", json=self.request | changes)
                self.assertEqual(response.status_code, 422)
        for field in ["query", "location"]:
            response = await self.client.post("/api/v1/leads/discover", json=self.request | {field: " "})
            self.assertEqual(response.status_code, 400)
        self.places.search.assert_not_awaited()

    async def test_query_location_are_stripped(self):
        response = await self.client.post("/api/v1/leads/discover", json=self.request | {"query": " agency ", "location": " Nashik "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["query"], "agency")
        self.assertEqual(self.places.search.call_args.kwargs["location"], "Nashik")

    async def test_no_results_api(self):
        app.state.lead_discovery_service = pipeline([])[0]
        response = await self.client.post("/api/v1/leads/discover", json=self.request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["leads"], [])
        self.assertEqual(response.json()["count"], 0)

    async def test_scraper_fallback_metadata_through_api(self):
        self.places.search.side_effect = PlacesConfigurationError("Missing Places API key")
        response = await self.client.post("/api/v1/leads/discover", json=self.request | {"priority": "high"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "google_maps_browser")
        self.assertTrue(response.json()["fallback_used"])
        self.assertNotIn("fallback_used", response.json()["leads"][0]["discovery"])

    async def test_removed_search_route_is_unavailable(self):
        request = {key: value for key, value in self.request.items() if key != "priority"}
        response = await self.client.post("/api/search", json=request | {"qualification": "partially_qualified"})
        self.assertEqual(response.status_code, 404)
        self.places.search.assert_not_awaited()

    async def test_openapi_exposes_only_canonical_discovery_and_dispatch_routes(self):
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        for path in ("/api/search", "/api/outreach/voice/call"):
            self.assertNotIn(path, schema["paths"])
        for path in ("/api/v1/leads/discover", "/api/v1/calls/dispatch"):
            self.assertIn("post", schema["paths"][path])
        self.assertEqual(schema["paths"]["/api/v1/calls/dispatch"]["post"]["security"],
                         [{"LeadSutraBearer": []}])
        for name in ("SearchRequest", "SearchResponse"):
            self.assertNotIn(name, schema["components"]["schemas"])

    async def test_existing_pipeline_error_statuses_are_preserved(self):
        for error, status in [(ValueError("fixture invalid input"), 400),
                              (RuntimeError("fixture provider failure"), 500)]:
            with self.subTest(error=error):
                app.state.lead_discovery_service = SimpleNamespace(run=AsyncMock(side_effect=error))
                response = await self.client.post("/api/v1/leads/discover", json=self.request)
                self.assertEqual(response.status_code, status)

    async def test_invalid_output_is_reported_as_server_error(self):
        app.state.lead_discovery_service = SimpleNamespace(run=AsyncMock(
            return_value=LeadDiscoveryRunResult(leads=[{"lead_id": "bad", "business": {}}])
        ))
        response = await self.client.post("/api/v1/leads/discover", json=self.request)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["message"], "Invalid pipeline output.")


if __name__ == "__main__":
    unittest.main()
