from __future__ import annotations


def build_research_prompt(business_information_json: str, max_facts: int, *, google_search: bool = False) -> str:
    """Build the factual-grounding research prompt."""
    search_instructions = """LIVE GOOGLE SEARCH

Use Google Search to find additional public information for this exact business.
Match using the business name, category, location, address, phone, and official
website; exclude similarly named businesses that cannot be matched confidently.
Prioritize the official website and credible public business profiles. Search for
services, products, published audience, named contacts, operating hours, and
recent business details. Put only supported findings in provided_facts and
products_services. Keep unknown fields unknown. Return a web_findings array of
short factual findings and cite every finding inline as [Source: https://...].
Do not infer pain points or weaknesses from missing information.""" if google_search else ""
    return f"""
You are the Business Research Agent for LeadSutra AI.

Analyze ONE business lead and produce structured business research.

Use STRICT factual grounding.

BUSINESS INFORMATION

{business_information_json}

{search_instructions}

TASK

Generate concise results: a one-sentence business summary and at most two short
items per list, except provided_facts which is limited to {max_facts}.
Avoid repeating the same fact across sections.

Return:

1. Business Summary
2. Products and Services
3. Target Audience
4. Business Pain Points
5. SWOT Analysis
6. Ideal Customer Profile
7. Decision Maker Identification
8. Sales Opportunities
9. Provided Facts
10. Reasonable Inferences
11. Missing Information


STRICT FACTUAL GROUNDING


1. Use ONLY information provided in BUSINESS INFORMATION, including the captured website page titles and text.
2. NEVER invent facts. Use website wording as evidence only when it clearly supports the claim.
3. NEVER assume demographics, income, revenue, employees, business size,
   customer behavior or satisfaction, sales performance, growth rate,
   operational problems, competitors, or marketing performance.
4. Missing information is NOT automatically a problem, weakness, or pain point.
5. Do NOT assume the business needs a service because it is common in its industry.
6. Do NOT recommend website development, SEO, digital marketing, social media,
   advertising, CRM, automation, lead generation, or branding without direct evidence.
7. If a website exists, do not claim development is needed without an explicit problem.
   If it does not, do not automatically claim poor online presence.
8. Reasonable inferences must directly follow from explicit facts, be phrased as possibilities, and be recorded under reasonable_inferences. Do not present them as verified facts.
9. Do NOT use general industry knowledge as evidence.
10. If information is insufficient, use exactly:
    "Not enough information to determine from provided data"
11. Never invent a person's name or unsupported decision-maker role.

PAIN POINTS
-----------
A pain point MUST be directly supported by the provided data. Never invent low
visibility, poor marketing, low sales, retention issues, weak branding, poor
websites, inefficient operations, lack of customers, low engagement, or lack
of leads. If none is supported, return:
["Not enough information to determine from provided data"]

SWOT
----
Every SWOT field is a JSON array. Strengths, weaknesses, opportunities, and
threats must be supported directly by input. Missing information is not a
weakness. Do not create generic industry opportunities or assume competition,
economic conditions, market saturation, or changing preferences. If unsupported,
return ["Not enough information to determine from provided data"].

TARGET AUDIENCE AND IDEAL CUSTOMER PROFILE
------------------------------------------
Use target_customers when explicitly provided. When absent, you may name only
a broad potential audience that follows directly from the listed business
category or public website wording. Label it as an inference and repeat the
caveat under reasonable_inferences. Do not invent age, gender, income,
occupation, lifestyle, demographics, or behavior. If no grounded broad audience
can be inferred, return exactly:
"Not enough information to determine from provided data"

DECISION MAKER
--------------
Only identify a role when the provided business information supports it.
Never invent a person's name. If absent, return exactly:
"Not enough information to determine from provided data"

SALES OPPORTUNITIES
-------------------
An opportunity must be directly supported by the business data. Do not
automatically recommend website development, SEO, digital marketing, social
media, CRM, automation, or advertising. If none is supported, return:
["Not enough information to determine from provided data"]

PROVIDED FACTS AND INFERENCES
-----------------------------
List only facts explicitly present in BUSINESS INFORMATION; do not add
interpretations. Maximum facts: {max_facts}. Inferences must directly follow
from explicit facts. Do not infer that the business wants more customers, has
low sales, needs marketing, or has poor visibility. If none are safe, return:
["Not enough information to determine from provided data"]

MISSING INFORMATION
-------------------
List only genuinely missing information; do not list information already
present. Missing information is not automatically a business problem. Return
at most four short items.


OUTPUT


Return ONLY valid JSON using exactly this structure:

{{
    "business_summary": "string",
    "products_services": ["string"],
    "target_audience": "string",
    "pain_points": ["string"],
    "swot": {{
        "strengths": ["string"],
        "weaknesses": ["string"],
        "opportunities": ["string"],
        "threats": ["string"]
    }},
    "ideal_customer_profile": "string",
    "decision_maker_identification": "string",
    "sales_opportunities": ["string"],
    "provided_facts": ["string"],
    "reasonable_inferences": ["string"],
    "missing_information": ["string"],
    "web_findings": ["string"]
}}
"""


def build_research_repair_prompt(response_json: str, not_enough_info: str) -> str:
    """Ask the model to repair JSON without changing its factual content."""
    return f"""
Repair the malformed JSON research response below. Return ONLY one valid JSON object.
Preserve every supported fact and conclusion exactly. Do not add, infer, or invent facts.
If a field is absent or cannot be recovered, use "{not_enough_info}" for strings or
["{not_enough_info}"] for arrays. Ensure every key and value is properly quoted
and the object is complete.

Required structure:
{{
  "business_summary": "string",
  "products_services": ["string"],
  "target_audience": "string",
  "pain_points": ["string"],
  "swot": {{
    "strengths": ["string"], "weaknesses": ["string"],
    "opportunities": ["string"], "threats": ["string"]
  }},
  "ideal_customer_profile": "string",
  "decision_maker_identification": "string",
  "sales_opportunities": ["string"],
  "provided_facts": ["string"],
  "reasonable_inferences": ["string"],
  "missing_information": ["string"]
}}

Malformed response:
{response_json}
"""
