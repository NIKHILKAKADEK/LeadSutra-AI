from __future__ import annotations

import json
from typing import Any, Callable


def build_proposal_prompt(
    *,
    business_name: str,
    category: str,
    sub_category: str,
    description: str,
    services: list[Any],
    products: list[Any],
    target_customers: list[Any],
    website: str,
    about_info: Any,
    rating: Any,
    review_count: Any,
    website_analysis: dict[str, Any],
    research: dict[str, Any],
    context: str,
    compact_data: Callable[[Any], Any],
    not_enough_info: str,
    price_not_available: str,
) -> str:
    """Build the evidence-grounded proposal prompt from validated agent inputs."""
    return f"""
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
Look for explicit business problems, requirements or requested services,
documented gaps, and specific evidence-supported research opportunities.
A complementary service may be an optional recommendation only when
relevant to actual business evidence. Do not confuse possible improvement
with a proven business problem.

If no sufficiently supported need or opportunity exists, use the exact
fallback value specified below.

OUTREACH QUALITY
----------------
- Lead with one relevant, verifiable observation, not flattery.
- Explain the reason for contacting the business in one sentence.
- Use a permission-based call to action; do not imply prior contact.
- Keep the email between 70 and 130 words, excluding placeholders.
- Do not claim results, client history, a relationship, or familiarity
  unless the supplied information supports it.
- Use placeholders such as [Your name] where sender details are absent.
- Ask discovery questions instead of inventing the prospect's needs.
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
- Do not recommend rebuilding an existing website without evidence.
- Do not assume an undocumented feature is absent.
- Use RAG to explain how a relevant solution could be implemented.
- Every need must be traceable to evidence; deliverables must match
  the solution, and benefits must be potential benefits, not guarantees.
- Do not claim the business accepted the proposal.

BUSINESS SUMMARY
----------------
Summarize the supplied business information accurately. Add no claims.

IDENTIFIED NEEDS
----------------
Return up to 4 concise evidence-supported needs or opportunities.
If none can be supported, return:
["{not_enough_info}"]

PROPOSED SOLUTION
-----------------
Provide one coherent solution addressing identified needs. If no
supported need exists, return:
"{not_enough_info}"

DELIVERABLES
------------
Return up to 6 concrete deliverables matching the solution.
If no supported solution exists, return:
["{not_enough_info}"]

IMPLEMENTATION TIMELINE
-----------------------
Return up to 4 reasonable implementation phases only when a supported
solution exists. Do not imply agreed dates. Otherwise return:
["{not_enough_info}"]

EXPECTED BENEFITS
-----------------
Return up to 4 potential benefits linked to the solution. Do not
guarantee results. Otherwise return:
["{not_enough_info}"]

PRICING
-------
Never invent or estimate a price. Use a numeric price only when explicit
in the supplied information. Otherwise return:
"{price_not_available}"

NEXT STEPS
----------
For a supported proposal, suggest practical steps such as discussing
requirements, reviewing scope, and confirming deliverables. Do not imply
acceptance. Otherwise return:
["{not_enough_info}"]

OUTREACH ANGLE
--------------
State the evidence-supported reason to start a conversation. If no need
is evidenced, recommend a neutral discovery approach.

EMAIL SUBJECT OPTIONS
---------------------
Return 2 concise, specific subject lines without clickbait.

PERSONALIZED EMAIL
------------------
Write a ready-to-edit first-contact email. Use placeholders for unknown
sender, company, or service details.

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
