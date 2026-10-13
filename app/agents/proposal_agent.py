
import json
import logging
from typing import Any

from app.llm.provider import generate
from app.models.proposal import ProposalResult
from app.agents.research_agent import compact_data


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

    # 2. Build the actual prompt sent to the LLM.
    # IMPORTANT: Do not overwrite this prompt later.

    prompt = f"""
You are the Proposal Generation Agent for LeadSutra AI.

Create an outreach-ready, evidence-grounded proposal for ONE business.
The primary reader is a salesperson preparing a first contact, not
the prospect receiving a long unsolicited proposal. Keep copy concise,
human, low-pressure, and easy to personalize.

BUSINESS INFORMATION
--------------------
Business name: {business_name}
Category: {category}
Sub-category: {sub_category}
Description: {description}
Services: {json.dumps(compact_data(services), ensure_ascii=False)}
Products: {json.dumps(compact_data(products), ensure_ascii=False)}
Target customers: {json.dumps(compact_data(target_customers), ensure_ascii=False)}
Website: {website}
About information: {compact_data(about_info)}
Rating: {rating}
Review count: {review_count}
Website analysis:
{json.dumps(compact_data(website_analysis), ensure_ascii=False)}

STRUCTURED RESEARCH
-------------------
{json.dumps(compact_data(research), indent=2, ensure_ascii=False)}

RETRIEVED RAG KNOWLEDGE
-----------------------
{context}

SOURCE PRIORITY
---------------
1. Explicit business information and requirements.
2. Documented website or business findings.
3. Structured research.
4. RAG for relevant service knowledge and implementation details.

RAG is general knowledge. It does not prove that this business
has a problem or needs a particular service.

OPPORTUNITY IDENTIFICATION
--------------------------
Look for:
1. Explicit business problems.
2. Explicit requirements or requested services.
3. Documented gaps or missing capabilities.
4. Specific, evidence-supported opportunities from research.

A complementary service may be presented as an optional
recommendation only when its relevance is supported by actual
business evidence. Do not confuse a possible improvement with
a proven business problem.

If no sufficiently supported need or opportunity exists, use
the exact fallback value specified below.

OUTREACH QUALITY
---------------
- Lead with one relevant, verifiable observation, not flattery.
- Make the reason for contacting this business clear in one sentence.
- Use a permission-based call to action; do not imply prior contact.
- Keep the email between 70 and 130 words, excluding placeholders.
- Do not claim results, client history, a relationship, or familiarity
  unless those facts appear in the supplied information.
- Use placeholders such as [Your name] where sender details are absent.
- Ask useful discovery questions instead of inventing the prospect's needs.
- Avoid generic openings such as "I hope this email finds you well".

STRICT GROUNDING
----------------
- Never invent facts, customer complaints, requirements, or gaps.
- Never invent revenue, traffic, conversion rates, competitors,
  customer numbers, or financial information.
- Never assume poor marketing, low sales, poor SEO, low visibility,
  weak branding, or a lack of customers without evidence.
- Missing information is not automatically a business problem.
- Do not recommend website development merely because a website
  is missing from the supplied data.
- Do not recommend rebuilding a website when one already exists
  unless evidence supports that recommendation.
- Do not assume that an undocumented feature is absent.
- Use RAG to explain how a relevant solution could be implemented.
- Every identified need must be traceable to evidence.
- Every deliverable must correspond to the proposed solution.
- Benefits must be potential benefits, never guarantees.
- Do not claim the business accepted the proposal.

BUSINESS SUMMARY
----------------
Summarize the supplied business information accurately.
Do not add unsupported claims.

IDENTIFIED NEEDS
----------------
Return up to 4 concise needs or opportunities supported by evidence.
If none can be supported, return:
["{NOT_ENOUGH_INFO}"]

PROPOSED SOLUTION
-----------------
Provide one coherent solution that addresses the identified needs.
If no supported need exists, return:
"{NOT_ENOUGH_INFO}"

DELIVERABLES
------------
Return up to 6 concrete deliverables that match the solution.
If no supported solution exists, return:
["{NOT_ENOUGH_INFO}"]

IMPLEMENTATION TIMELINE
-----------------------
Return up to 4 reasonable implementation phases only when a
supported solution exists. Do not imply agreed dates.
Otherwise return:
["{NOT_ENOUGH_INFO}"]

EXPECTED BENEFITS
-----------------
Return up to 4 potential benefits linked to the solution.
Do not guarantee results.
Otherwise return:
["{NOT_ENOUGH_INFO}"]

PRICING
-------
Never invent or estimate a price.
Use a numeric price only when an explicit price is available
in the supplied information.
Otherwise return:
"{PRICE_NOT_AVAILABLE}"

NEXT STEPS
----------
When a supported proposal exists, suggest practical steps such as
discussing requirements, reviewing scope, and confirming deliverables.
Do not imply acceptance.
Otherwise return:
["{NOT_ENOUGH_INFO}"]

OUTREACH ANGLE
--------------
State the evidence-supported reason to start a conversation. If no
need is evidenced, explicitly recommend a neutral discovery approach.

EMAIL SUBJECT OPTIONS
---------------------
Return 2 concise, specific subject lines without clickbait.

PERSONALIZED EMAIL
------------------
Write a ready-to-edit first-contact email following the rules above.
Use placeholders for unknown sender, company, or service details.

CALL OPENER
-----------
Write a natural 1-2 sentence opener that asks permission to continue.

DISCOVERY QUESTIONS
-------------------
Return 3 open questions that help establish fit without presuming a problem.

OUTPUT RULES
------------
Return ONLY valid JSON, without Markdown or additional commentary.
Use exactly this structure:

{{
    "business_summary": "string",
    "identified_needs": ["string"],
    "proposed_solution": "string",
    "deliverables": ["string"],
    "implementation_timeline": ["string"],
    "expected_benefits": ["string"],
    "pricing_suggestion": "string",
    "next_steps": ["string"],
    "outreach_angle": "string",
    "email_subject_options": ["string"],
    "personalized_email": "string",
    "call_opener": "string",
    "discovery_questions": ["string"]
}}
"""

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
