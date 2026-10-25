"""Comprehensive test suite for LangGraph orchestration, RAG, research, and multi-agent workflow."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.agents.lead_pipeline.schemas import (
    BusinessRecord,
    CrawlError,
    DiscoveryData,
    EnrichmentData,
    LeadDiscoveryRunResult,
    LeadResult,
    ScoringData,
    WebsiteCrawlResult,
    WebsitePage,
    WebsiteStatus,
)
from app.graph.edges import (
    check_approval_for_outreach,
    check_discovery_success,
    check_lead_selected,
    check_proposal_success,
    check_query_valid,
    check_rag_success,
    check_research_success,
)
from app.graph.nodes import (
    lead_discovery_node,
    normalize_and_deduplicate_leads_node,
    parse_lead_query,
    persist_and_return_leads_node,
    persist_results_node,
    proposal_agent_node,
    rag_agent_node,
    record_outreach_result_node,
    research_agent_node,
    send_approved_outreach_node,
    validate_proposal_node,
    validate_query_node,
    validate_research_node,
    validate_retrieved_context_node,
    validate_selected_lead_node,
)
from app.graph.orchestrator import LeadSutraOrchestrator, build_leadsutra_graph
from app.graph.state import WorkflowState
from app.rag.vector_store import index_lead_research, retrieve_context_for_lead
from app.tools.extract_contacts import extract_emails_from_text, extract_phones_from_text
from app.tools.lead_adapter import adapt_lead
from app.tools.score_lead import score_lead_data


# ======================================================================
# FIXTURES
# ======================================================================

def sample_lead(lead_id: str = "lead_001", name: str = "Nashik Web Solutions") -> LeadResult:
    return LeadResult(
        lead_id=lead_id,
        discovery=DiscoveryData(
            business_name=name,
            category="Software Company",
            address="College Road, Nashik",
            phone="+919876543210",
            website="https://nashikwebsolutions.com",
            rating=4.8,
            source_url="https://maps.google.com/?q=test",
        ),
        enrichment=EnrichmentData(
            website_url="https://nashikwebsolutions.com",
            website_status=WebsiteStatus.ACTIVE,
            about="We build modern software and web applications for businesses.",
            services=["Custom Software", "Web Development", "Cloud Architecture"],
            emails=["contact@nashikwebsolutions.com"],
            phone_numbers=["+919876543210"],
        ),
        scoring=ScoringData(
            lead_score=88.0,
            priority="High",
            qualification_status="Qualified",
            score_breakdown={"has_website": 25, "has_phone": 20, "has_email": 25, "rating": 18},
        ),
    )


# ======================================================================
# TESTS: QUERY VALIDATION & PARSING
# ======================================================================

def test_query_parsing_natural_language():
    cat, loc = parse_lead_query("Find software development companies in Nashik")
    assert cat.lower() == "software development companies"
    assert loc.lower() == "nashik"

    cat, loc = parse_lead_query("Digital marketing agency", explicit_location="Pune")
    assert cat == "Digital marketing agency"
    assert loc == "Pune"


@pytest.mark.asyncio
async def test_validate_query_node_valid():
    state: WorkflowState = {
        "user_query": "Find dentists in Nashik",
        "search_location": "",
    }
    result = await validate_query_node(state)
    assert result["business_category"] == "dentists"
    assert result["search_location"] == "Nashik"
    assert result["execution_status"] == "QUERY_VALIDATED"
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_validate_query_node_invalid_missing_location():
    state: WorkflowState = {
        "user_query": "dentists",
        "search_location": "",
    }
    result = await validate_query_node(state)
    assert result["execution_status"] == "FAILED"
    assert any("location" in err.lower() for err in result["errors"])


# ======================================================================
# TESTS: LEAD DISCOVERY & DEDUPLICATION (MOCKED)
# ======================================================================

@pytest.mark.asyncio
async def test_lead_discovery_mocked():
    lead = sample_lead()
    mock_run_result = LeadDiscoveryRunResult(
        leads=[lead],
        source="google_places",
        fallback_used=False,
    )

    with patch("app.graph.nodes.LeadPipeline.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_run_result
        state: WorkflowState = {
            "business_category": "Software Company",
            "search_location": "Nashik",
            "discovery_limit": 5,
        }
        res = await lead_discovery_node(state)
        assert res["execution_status"] == "LEADS_DISCOVERED"
        assert res["candidates_count"] == 1
        assert res["discovered_leads"][0]["lead_id"] == "lead_001"


@pytest.mark.asyncio
async def test_normalize_and_deduplicate_leads():
    lead1 = sample_lead("lead_001").model_dump(mode="json")
    lead2 = sample_lead("lead_001").model_dump(mode="json")
    lead3 = sample_lead("lead_002", "Apex Tech").model_dump(mode="json")

    state: WorkflowState = {
        "discovered_leads": [lead1, lead2, lead3],
    }
    res = await normalize_and_deduplicate_leads_node(state)
    assert res["candidates_count"] == 2
    assert len(res["discovered_leads"]) == 2


@pytest.mark.asyncio
async def test_persist_and_pause_for_selection():
    state: WorkflowState = {
        "discovered_leads": [sample_lead().model_dump(mode="json")],
    }
    res = await persist_and_return_leads_node(state)
    assert res["execution_status"] == "WAITING_FOR_USER_SELECTION"


# ======================================================================
# TESTS: LEAD SELECTION VALIDATION & RESUMPTION
# ======================================================================

@pytest.mark.asyncio
async def test_validate_selected_lead_success():
    lead_dict = sample_lead("lead_001").model_dump(mode="json")
    state: WorkflowState = {
        "discovered_leads": [lead_dict],
        "selected_lead_id": "lead_001",
    }
    res = await validate_selected_lead_node(state)
    assert res["execution_status"] == "LEAD_VALIDATED"
    assert res["selected_lead"]["lead_id"] == "lead_001"
    assert res["lead_score"] == 88.0


@pytest.mark.asyncio
async def test_validate_selected_lead_missing():
    state: WorkflowState = {
        "discovered_leads": [],
        "selected_lead_id": "non_existent_id",
    }
    res = await validate_selected_lead_node(state)
    assert res["execution_status"] == "FAILED"
    assert any("not found" in err for err in res["errors"])


# ======================================================================
# TESTS: RESEARCH EXTRACTION & CRAWLER FAILURE HANDLING
# ======================================================================

@pytest.mark.asyncio
async def test_research_agent_with_crawled_content():
    lead_dict = sample_lead("lead_001").model_dump(mode="json")
    mock_research_output = {
        "business_summary": "Nashik Web Solutions provides enterprise software and cloud consulting.",
        "products_services": ["Custom Software", "Web Development", "Cloud Architecture"],
        "target_audience": "Local and regional businesses requiring IT modernization",
        "pain_points": ["Not enough information to determine from provided data"],
        "swot": {
            "strengths": ["Strong online presence", "Rating of 4.8"],
            "weaknesses": ["Not enough information to determine from provided data"],
            "opportunities": ["Not enough information to determine from provided data"],
            "threats": ["Not enough information to determine from provided data"],
        },
        "ideal_customer_profile": "Mid-market businesses seeking web transformation",
        "decision_maker_identification": "Not enough information to determine from provided data",
        "sales_opportunities": ["Not enough information to determine from provided data"],
        "provided_facts": ["Rating is 4.8", "Offers Custom Software"],
        "reasonable_inferences": ["Operates in Software Company category"],
        "missing_information": ["Review count"],
    }

    with patch("app.graph.nodes.research_agent", return_value=mock_research_output):
        state: WorkflowState = {
            "selected_lead": lead_dict,
        }
        res = await research_agent_node(state)
        assert res["execution_status"] == "RESEARCH_COMPLETED"
        assert res["research_results"]["business_summary"].startswith("Nashik Web Solutions")


@pytest.mark.asyncio
async def test_website_crawler_failure_resilience():
    lead_dict = sample_lead("lead_001").model_dump(mode="json")
    mock_crawl = WebsiteCrawlResult(
        lead_id="lead_001",
        website_url="https://nashikwebsolutions.com",
        website_status=WebsiteStatus.UNREACHABLE,
        crawl_errors=[CrawlError(url="https://nashikwebsolutions.com", message="Connection timed out")],
    )

    with patch("app.integrations.website_fetcher.WebsiteCrawler.crawl", new_callable=AsyncMock, return_value=mock_crawl), \
         patch("app.graph.nodes.research_agent") as mock_agent:
        mock_agent.return_value = {
            "business_summary": "Company listed in Nashik.",
            "products_services": [],
            "target_audience": "Not enough information to determine from provided data",
            "pain_points": ["Not enough information to determine from provided data"],
            "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
            "ideal_customer_profile": "Not enough information to determine from provided data",
            "decision_maker_identification": "Not enough information to determine from provided data",
            "sales_opportunities": ["Not enough information to determine from provided data"],
            "provided_facts": ["Name is Nashik Web Solutions"],
            "reasonable_inferences": [],
            "missing_information": ["Website content"],
        }
        state: WorkflowState = {"selected_lead": lead_dict}
        res = await research_agent_node(state)
        assert res["execution_status"] == "RESEARCH_COMPLETED"


# ======================================================================
# TESTS: RAG CHUNKING, INDEXING & GROUNDED RETRIEVAL
# ======================================================================

def test_rag_lead_indexing_and_retrieval():
    lead_id = "test_lead_unique_42"
    research_data = {
        "business_summary": "Apex Dental Clinic specializes in painless root canal and orthodontics in Nashik.",
        "products_services": ["Painless Root Canal", "Teeth Whitening", "Orthodontics"],
        "provided_facts": ["Experienced dental surgeons on staff", "Advanced 3D imaging"],
    }

    # Index into ChromaDB
    chunks_count = index_lead_research(
        lead_id=lead_id,
        business_name="Apex Dental Clinic",
        research=research_data,
    )
    assert chunks_count > 0

    # Retrieve context strictly for this lead
    retrieved = retrieve_context_for_lead(
        lead_id=lead_id,
        query="What treatments does Apex Dental Clinic provide?",
        k=3,
    )
    assert len(retrieved) > 0
    contents = [d.page_content for d in retrieved]
    assert any("Root Canal" in c or "Dental" in c for c in contents)


# ======================================================================
# TESTS: PROPOSAL GENERATION & VALIDATION
# ======================================================================

@pytest.mark.asyncio
async def test_proposal_agent_node_grounded():
    lead_dict = sample_lead("lead_001").model_dump(mode="json")
    mock_proposal = {
        "business_summary": "Nashik Web Solutions provides enterprise software and cloud consulting.",
        "identified_needs": ["Not enough information to determine from provided data"],
        "proposed_solution": "Modern web development and cloud architectural enhancement",
        "deliverables": ["Interactive frontend redesign", "Cloud performance audit"],
        "implementation_timeline": ["4 to 6 weeks"],
        "expected_benefits": ["Improved user engagement and higher search visibility"],
        "pricing_suggestion": "Not available from provided data",
        "next_steps": ["Schedule a 15-minute introductory consultation"],
        "outreach_angle": "Start with respectful introduction regarding tech stack alignment",
        "email_subject_options": ["Web development collaboration with Nashik Web Solutions"],
        "personalized_email": "Hi Team,\n\nI noticed your work in software development in Nashik...",
        "call_opener": "Hi, this is Alex reaching out regarding your web engineering capabilities...",
        "discovery_questions": ["What are your primary technology initiatives this quarter?"],
    }

    with patch("app.graph.nodes.proposal_agent", return_value=mock_proposal):
        state: WorkflowState = {
            "selected_lead": lead_dict,
            "research_results": {"business_summary": "Summary"},
            "retrieved_context": [{"content": "Grounded context"}],
        }
        res = await proposal_agent_node(state)
        assert res["execution_status"] == "PROPOSAL_GENERATED"
        assert res["proposal"]["proposed_solution"].startswith("Modern web development")
        assert "Web development collaboration" in res["outreach_email"]["subject"]


# ======================================================================
# TESTS: PERSISTENCE, APPROVAL & OUTREACH GATING
# ======================================================================

@pytest.mark.asyncio
async def test_persist_results_node_saves_proposal():
    lead_dict = sample_lead("lead_001").model_dump(mode="json")
    proposal_dict = {
        "business_summary": "Test Summary",
        "identified_needs": [],
        "proposed_solution": "Test Solution",
        "deliverables": ["Audit"],
        "implementation_timeline": ["2 weeks"],
        "expected_benefits": ["Efficiency"],
        "pricing_suggestion": "Not available from provided data",
        "next_steps": ["Follow up"],
    }
    with TemporaryDirectory() as tmp_dir, patch("app.graph.nodes.get_settings") as mock_settings:
        mock_settings.return_value.proposal_root = str(tmp_dir)
        state: WorkflowState = {
            "selected_lead": lead_dict,
            "proposal": proposal_dict,
        }
        res = await persist_results_node(state)
        assert res["execution_status"] == "WAITING_FOR_USER_APPROVAL"
        assert res["approval_status"] == "pending"

        saved_file = Path(tmp_dir) / "lead_001" / "proposal.json"
        assert saved_file.is_file()


@pytest.mark.asyncio
async def test_send_approved_outreach_blocked_without_approval():
    state: WorkflowState = {
        "approval_status": "pending",
        "outreach_channel": "email",
    }
    res = await send_approved_outreach_node(state)
    assert res["execution_status"] == "WAITING_FOR_USER_APPROVAL"
    assert res["outreach_result"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_send_approved_outreach_dry_run_when_disabled():
    state: WorkflowState = {
        "approval_status": "approved",
        "outreach_channel": "email",
        "selected_lead": sample_lead("lead_001").model_dump(mode="json"),
        "outreach_email": {"subject": "Intro", "body": "Hello"},
    }
    with patch("app.graph.nodes.get_email_settings") as mock_settings:
        mock_settings.return_value.email_sending_enabled = False
        res = await send_approved_outreach_node(state)
        assert res["execution_status"] == "OUTREACH_EXECUTED"
        assert res["outreach_result"]["status"] == "dry_run"


# ======================================================================
# TESTS: FULL LANGGRAPH ORCHESTRATOR END-TO-END WORKFLOW
# ======================================================================

@pytest.mark.asyncio
async def test_orchestrator_complete_lifecycle():
    with TemporaryDirectory() as tmp_dir:
        orch = LeadSutraOrchestrator(storage_dir=tmp_dir)
        lead = sample_lead("lead_test_lifecycle")

        # 1. Start discovery (Mocked Places)
        mock_run = LeadDiscoveryRunResult(leads=[lead], source="google_places", fallback_used=False)
        with patch("app.graph.nodes.LeadPipeline.run", new_callable=AsyncMock, return_value=mock_run):
            state = await orch.start_discovery(
                query="software development in Nashik",
                limit=5,
            )
            assert state["execution_status"] == "WAITING_FOR_USER_SELECTION"
            assert len(state["discovered_leads"]) == 1
            wf_id = state["workflow_id"]

        # 2. Select lead and resume (Mocked Research & Proposal LLM)
        mock_res = {
            "business_summary": "Nashik Web Solutions is a leading tech agency.",
            "products_services": ["Web Apps", "Cloud"],
            "target_audience": "Enterprises",
            "pain_points": ["Not enough information to determine from provided data"],
            "swot": {"strengths": ["Top rated"], "weaknesses": [], "opportunities": [], "threats": []},
            "ideal_customer_profile": "CTOs and founders",
            "decision_maker_identification": "Founder",
            "sales_opportunities": [],
            "provided_facts": ["Based in Nashik"],
            "reasonable_inferences": [],
            "missing_information": [],
        }
        mock_prop = {
            "business_summary": "Nashik Web Solutions is a leading tech agency.",
            "identified_needs": ["Not enough information to determine from provided data"],
            "proposed_solution": "Full-stack development partner",
            "deliverables": ["Scalable architecture"],
            "implementation_timeline": ["1 month"],
            "expected_benefits": ["Faster time to market"],
            "pricing_suggestion": "Not available from provided data",
            "next_steps": ["Intro call"],
            "email_subject_options": ["Collaboration opportunity"],
            "personalized_email": "Hi Team, let us connect.",
        }

        mock_crawl = WebsiteCrawlResult(
            lead_id="lead_test_lifecycle",
            website_status=WebsiteStatus.UNREACHABLE,
        )
        with patch("app.graph.nodes.research_agent", return_value=mock_res), \
             patch("app.graph.nodes.proposal_agent", return_value=mock_prop), \
             patch("app.integrations.website_fetcher.WebsiteCrawler.crawl", new_callable=AsyncMock, return_value=mock_crawl):
            res_state = await orch.select_lead_and_resume(wf_id, lead_id="lead_test_lifecycle")
            assert res_state["execution_status"] == "WAITING_FOR_USER_APPROVAL"
            assert res_state["selected_lead_id"] == "lead_test_lifecycle"
            assert res_state["proposal"]["proposed_solution"] == "Full-stack development partner"

        # 3. Explicitly approve proposal and execute outreach
        with patch("app.graph.nodes.get_email_settings") as mock_email_settings:
            mock_email_settings.return_value.email_sending_enabled = False
            outreach_state = await orch.approve_and_send_outreach(
                wf_id,
                channel="email",
            )
            assert outreach_state["approval_status"] == "approved"
            assert outreach_state["execution_status"] == "COMPLETED"
            assert outreach_state["outreach_result"]["status"] == "dry_run"


# ======================================================================
# TESTS: TOOLS REGISTRY & CONTACT EXTRACTION
# ======================================================================

def test_extract_emails_and_phones():
    text = "Call us at +91 98765 43210 or 9822012345 or email info@testdomain.com, hello@testdomain.com."
    emails = extract_emails_from_text(text)
    assert "info@testdomain.com" in emails
    assert "hello@testdomain.com" in emails

    phones = extract_phones_from_text(text)
    assert any("9876543210" in p for p in phones)
    assert any("9822012345" in p for p in phones)
