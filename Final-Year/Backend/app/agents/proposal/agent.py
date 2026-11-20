import json
import logging
from typing import Any

from app.llm.provider import generate
from app.agents.proposal.schema import ProposalResult
from app.agents.research.agent import compact_data
from app.agents.proposal.prompt import build_proposal_prompt


logger = logging.getLogger(__name__)

NOT_ENOUGH_INFO = "Not enough information to determine from provided data"
PRICE_NOT_AVAILABLE = "Not available from provided data"

PROPOSAL_LIST_FIELDS = (
    "identified_needs",
    "deliverables",
    "implementation_timeline",
    "expected_benefits",
    "next_steps",
    "email_subject_options",
    "discovery_questions",
)

EXPLICIT_EVIDENCE_FIELDS = (
    "business_needs",
    "requirements",
    "pain_points",
    "requested_services",
    "business_goals",
)

DOCUMENTED_GAP_FIELDS = (
    "issues",
    "gaps",
    "missing_features",
    "documented_gaps",
)


def is_available(value: Any) -> bool:
    """Check whether a value contains usable information."""

    if value is None:
        return False

    if isinstance(value, str):
        value = value.strip()
        return bool(value) and value.casefold() not in {
            NOT_ENOUGH_INFO.casefold(),
            PRICE_NOT_AVAILABLE.casefold(),
            "unknown",
            "none",
            "null",
            "not available",
        }

    if isinstance(value, list):
        return any(is_available(item) for item in value)

    if isinstance(value, dict):
        return any(is_available(item) for item in value.values())

    return bool(value)


def normalize_proposal_data(data: dict) -> dict:
    """Normalize LLM output before Pydantic validation."""

    if not isinstance(data, dict):
        raise ValueError("Proposal output must be a JSON object.")

    normalized = dict(data)

    for field in PROPOSAL_LIST_FIELDS:
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = [value]
        elif value is None:
            normalized[field] = []

        if not isinstance(normalized.get(field), list):
            raise ValueError(
                f"Proposal field '{field}' must be a string or list."
            )

    return normalized


def has_supported_items(value: Any) -> bool:
    """Check whether evidence contains a meaningful statement."""

    return is_available(value)


def has_documented_evidence(lead: dict, research: dict) -> bool:
    """
    Check whether a proposal has a documented basis.

    Evidence may come from explicit lead requirements, documented
    website-analysis gaps, or research-supported opportunities.

    RAG context alone is never sufficient evidence of business need.
    """

    # Explicit needs or requirements from the lead source.
    for field in EXPLICIT_EVIDENCE_FIELDS:
        if has_supported_items(lead.get(field)):
            return True

    # Explicit evidence recorded by the research agent.
    if has_supported_items(research.get("sales_opportunities")):
        return True

    # A pain point counts only if research identifies one rather
    # than returning the standard missing-information fallback.
    if has_supported_items(research.get("pain_points")):
        return True

    # Documented gaps from website analysis.
    website_analysis = lead.get("website_analysis") or {}

    if not isinstance(website_analysis, dict):
        website_analysis = {}

    for field in DOCUMENTED_GAP_FIELDS:
        if has_supported_items(website_analysis.get(field)):
            return True

    return False


def ground_proposal_result(
    research: dict,
    lead: dict,
    data: dict,
) -> dict:
    """
    Prevent a proposal from inventing a business need when no
    qualifying evidence has been provided.
    """

    if not has_documented_evidence(lead, research):
        logger.info(
            "No documented proposal need found for business: %s",
            lead.get("business_name", "Unknown Business"),
        )

        business_name = lead.get("business_name") or "your business"
        category = lead.get("category") or lead.get("sub_category")
        location = lead.get("address")
        observed_context = ""
        if category:
            observed_context = f" and noticed it is listed as a {category}"
        elif location:
            observed_context = f" and noticed the listing at {location}"

        summary = research.get("business_summary")
        if not summary:
            description = lead.get("description") or lead.get("business_description")
            summary = (
                f"{business_name}: {description}"
                if description
                else f"{business_name} is a business listed in the supplied lead data."
            )

        return {
            "business_summary": summary,
            "identified_needs": [NOT_ENOUGH_INFO],
            "proposed_solution": NOT_ENOUGH_INFO,
            "deliverables": [NOT_ENOUGH_INFO],
            "implementation_timeline": [NOT_ENOUGH_INFO],
            "expected_benefits": [NOT_ENOUGH_INFO],
            "pricing_suggestion": PRICE_NOT_AVAILABLE,
            "next_steps": [
                "Ask whether a short discovery conversation would be useful; do not pitch a service until a need is confirmed."
            ],
            "outreach_angle": "Start with a respectful introduction and ask permission to learn about current priorities; no specific need is evidenced yet.",
            "email_subject_options": [
                f"A quick question for {business_name}",
                "Would a brief introduction be useful?",
            ],
            "personalized_email": (
                f"Hi,\n\nI came across {business_name}{observed_context}. "
                "I don't want to assume what your priorities are. "
                "I work with [type of business] on [specific service], and wanted to ask whether a brief conversation would be relevant. "
                "If so, would you be open to a 15-minute introduction? If not, no problem.\n\n"
                "Best,\n[Your name]\n[Your company]"
            ),
            "call_opener": (
                f"Hi, this is [your name] from [your company]. I came across {business_name}"
                f"{observed_context}. I don't want to assume you need anything; may I take 20 seconds to explain why I called, then you can tell me if a follow-up is relevant?"
            ),
            "discovery_questions": [
                "What are your main priorities for the next few months?",
                "Are there any areas where you are currently looking for outside support?",
                "What would make a follow-up conversation useful for you?",
            ],
        }

    return data


def proposal_agent(
    lead: dict,
    research: dict | None = None,
    retrieved_context: list[str | dict[str, str]] | None = None,
) -> dict:
    """
    Generate a personalized proposal using lead data, structured
    research, and relevant RAG context.
    """

    # Inputs are explicit and independently produced by their own endpoints.
    lead = lead or {}
    research = research or {}
    retrieved_context = retrieved_context or []

    if not isinstance(lead, dict):
        raise ValueError("Lead data must be a dictionary.")

    if not isinstance(research, dict):
        raise ValueError("Research data must be a dictionary.")

    business_name = lead.get("business_name") or "Unknown Business"
    category = lead.get("category") or "Not available"
    sub_category = lead.get("sub_category") or "Not available"
    description = lead.get("description") or "Not available"

    services = (lead.get("services") or [])[:20]
    products = (lead.get("products") or [])[:10]
    target_customers = (lead.get("target_customers") or [])[:10]

    website = lead.get("website") or "Not available"
    about_info = lead.get("about_info") or "Not available"

    rating = lead.get("rating")
    review_count = lead.get("review_count")

    website_analysis = lead.get("website_analysis") or {}

    # Convert RAG documents to safe text.
    context_parts = []

    for item in retrieved_context[:4]:
        if isinstance(item, str):
            context_parts.append(item)
        elif isinstance(item, dict):
            context_parts.append(
                json.dumps(item, ensure_ascii=False)
            )
        else:
            context_parts.append(str(item))

    context = (
        "\n\n".join(context_parts)
        if context_parts
        else "No relevant knowledge retrieved."
    )

    prompt = build_proposal_prompt(
        business_name=business_name,
        category=category,
        sub_category=sub_category,
        description=description,
        services=services,
        products=products,
        target_customers=target_customers,
        website=website,
        about_info=about_info,
        rating=rating,
        review_count=review_count,
        website_analysis=website_analysis,
        research=research,
        context=context,
        compact_data=compact_data,
        not_enough_info=NOT_ENOUGH_INFO,
        price_not_available=PRICE_NOT_AVAILABLE,
    )

    # 3. Call the configured LLM provider.
    # This is the only prompt used for proposal generation.

    proposal_text = generate(prompt, task="proposal")

    # 4. Parse the returned JSON.
    if isinstance(proposal_text, dict):
        proposal_data = proposal_text
    else:
        text_response = str(proposal_text).strip()

        # Handle providers that wrap JSON in a Markdown code fence.
        if text_response.startswith("```"):
            lines = text_response.splitlines()

            if lines and lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            text_response = "\n".join(lines).strip()

        try:
            proposal_data = json.loads(text_response)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Proposal Agent returned invalid JSON: {error}"
            ) from error

    # 5. Normalize, ground, and validate the result.
    try:
        normalized_data = normalize_proposal_data(proposal_data)

        grounded_data = ground_proposal_result(
            research=research,
            lead=lead,
            data=normalized_data,
        )

        proposal_result = ProposalResult(**grounded_data)

    except Exception as error:
        raise ValueError(
            f"Proposal Agent output failed validation: {error}"
        ) from error

    # Return only the proposal; no downstream agent is invoked here.
    logger.info(
        "Proposal generated for business: %s",
        business_name,
    )

    return proposal_result.model_dump()
