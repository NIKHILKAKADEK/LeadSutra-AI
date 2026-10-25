import json
import logging
from typing import Any

from app.llm.provider import generate
from app.models.research import ResearchResult

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

NOT_ENOUGH_INFO = "Not enough information to determine from provided data"

# Output limits
MAX_SERVICES_IN_OUTPUT = 15
MAX_FACTS = 12
MAX_INFERENCES = 3
MAX_MISSING_INFORMATION = 8

# Input limits
MAX_SERVICES_FOR_LLM = 8
MAX_PRODUCTS_FOR_LLM = 5
MAX_TARGET_CUSTOMERS_FOR_LLM = 5

MAX_STRING_LENGTH = 300
MAX_DESCRIPTION_LENGTH = 800
MAX_ABOUT_LENGTH = 500

MAX_NESTED_ITEMS = 5
MAX_NESTED_DEPTH = 3

RESEARCH_LIST_FIELDS = (
    "products_services",
    "pain_points",
    "sales_opportunities",
    "provided_facts",
    "reasonable_inferences",
    "missing_information",
)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_research_data(data: dict) -> dict:
    """
    Normalize harmless scalar/list differences before validation.
    """

    normalized = dict(data)

    for field in RESEARCH_LIST_FIELDS:
        if isinstance(normalized.get(field), str):
            normalized[field] = [normalized[field]]

    swot = normalized.get("swot")

    if isinstance(swot, dict):
        normalized_swot = dict(swot)

        for field in (
            "strengths",
            "weaknesses",
            "opportunities",
            "threats",
        ):
            if isinstance(normalized_swot.get(field), str):
                normalized_swot[field] = [normalized_swot[field]]

        normalized["swot"] = normalized_swot

    return normalized


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def truncate_text(value: Any, max_length: int = MAX_STRING_LENGTH):
    """
    Convert a value to string and safely truncate it.
    """

    if value is None:
        return None

    text = str(value).strip()

    if len(text) <= max_length:
        return text

    return text[:max_length] + "... [truncated]"


def compact_data(
    value,
    max_items=MAX_NESTED_ITEMS,
    max_string_length=MAX_STRING_LENGTH,
    depth=0,
):
    """
    Recursively compact dictionaries/lists before sending them
    to the LLM.
    """

    if value is None:
        return None

    # String
    if isinstance(value, str):
        return truncate_text(value, max_string_length)

    # Numbers / booleans
    if isinstance(value, (int, float, bool)):
        return value

    # List
    if isinstance(value, list):

        if depth >= MAX_NESTED_DEPTH:
            return [
                truncate_text(item, max_string_length)
                if isinstance(item, str)
                else str(item)
                for item in value[:max_items]
            ]

        return [
            compact_data(
                item,
                max_items=max_items,
                max_string_length=max_string_length,
                depth=depth + 1,
            )
            for item in value[:max_items]
        ]

    # Dictionary
    if isinstance(value, dict):

        if depth >= MAX_NESTED_DEPTH:
            return {
                str(key): (
                    truncate_text(val, max_string_length)
                    if isinstance(val, str)
                    else str(val)
                )
                for key, val in list(value.items())[:max_items]
            }

        compacted = {}

        for key, val in list(value.items())[:max_items]:
            compacted[str(key)] = compact_data(
                val,
                max_items=max_items,
                max_string_length=max_string_length,
                depth=depth + 1,
            )

        return compacted

    return truncate_text(value, max_string_length)


# ============================================================
# MISSING INFORMATION
# ============================================================

def _missing_information(lead: dict) -> list[str]:
    """
    Determine genuinely missing information from the original lead.
    """

    fields = (
        ("products", "Products"),
        ("target_customers", "Target customers"),
        ("website", "Website"),
        ("address", "Address"),
        ("email", "Email address"),
        ("review_count", "Review count"),
    )

    missing = []

    for key, label in fields:
        value = lead.get(key)

        if value is None:
            missing.append(label)
            continue

        if isinstance(value, str) and not value.strip():
            missing.append(label)
            continue

        if isinstance(value, list) and not value:
            missing.append(label)
            continue

        if isinstance(value, dict) and not value:
            missing.append(label)

    return missing[:MAX_MISSING_INFORMATION] or [NOT_ENOUGH_INFO]


# ============================================================
# LIST CLEANER
# ============================================================

def _clean_list(value, maximum: int) -> list[str]:
    """
    Clean a list of strings.
    """

    if not isinstance(value, list):
        return []

    cleaned = []

    for item in value:
        if isinstance(item, str):
            item = item.strip()

            if item:
                cleaned.append(item)

    return list(dict.fromkeys(cleaned))[:maximum]


# ============================================================
# GROUND RESEARCH RESULT
# ============================================================

def ground_research_result(lead: dict, data: dict) -> dict:
    """
    Build the final research result.

    IMPORTANT:
    The LLM is used for analysis, but unsupported claims are not
    trusted automatically.

    Deterministic lead data is preferred whenever possible.
    """

    name = lead.get("business_name") or "This business"

    # --------------------------------------------------------
    # BUSINESS SUMMARY
    # --------------------------------------------------------

    description = truncate_text(
        lead.get("description")
        or lead.get("business_description"),
        300,
    )

    business_summary = data.get("business_summary")

    if not isinstance(business_summary, str) or not business_summary.strip():
        if description:
            business_summary = f"{name}: {description}"
        else:
            business_summary = name

    # --------------------------------------------------------
    # PRODUCTS / SERVICES
    # --------------------------------------------------------

    provided_services = [
        str(service).strip()
        for service in (lead.get("services") or [])
        if str(service).strip()
    ]

    provided_products = [
        str(product).strip()
        for product in (lead.get("products") or [])
        if str(product).strip()
    ]

    # Only use items that actually exist in lead data.
    allowed_items = {
        item.lower(): item
        for item in provided_services + provided_products
    }

    llm_products_services = data.get("products_services") or []

    grounded_products_services = []

    for item in llm_products_services:

        if not isinstance(item, str):
            continue

        item = item.strip()

        if item.lower() in allowed_items:
            grounded_products_services.append(
                allowed_items[item.lower()]
            )

    # If LLM did not return valid items, use actual lead data.
    if not grounded_products_services:

        grounded_products_services = (
            provided_services[:MAX_SERVICES_IN_OUTPUT]
            or provided_products[:MAX_SERVICES_IN_OUTPUT]
            or [NOT_ENOUGH_INFO]
        )

    grounded_products_services = list(
        dict.fromkeys(grounded_products_services)
    )[:MAX_SERVICES_IN_OUTPUT]

    # --------------------------------------------------------
    # TARGET AUDIENCE
    # --------------------------------------------------------

    target_customers = lead.get("target_customers") or []

    if target_customers:

        target_audience = ", ".join(
            str(customer).strip()
            for customer in target_customers[:MAX_TARGET_CUSTOMERS_FOR_LLM]
            if str(customer).strip()
        )

        if not target_audience:
            target_audience = NOT_ENOUGH_INFO

    else:
        target_audience = NOT_ENOUGH_INFO

    # --------------------------------------------------------
    # PAIN POINTS
    # --------------------------------------------------------
    #
    # IMPORTANT:
    # Do NOT trust generic LLM guesses here.
    #
    # Missing information is NOT a pain point.
    # Industry assumptions are NOT pain points.
    #

    pain_points = [NOT_ENOUGH_INFO]

    # --------------------------------------------------------
    # SWOT
    # --------------------------------------------------------
    #
    # We only create strengths from explicit facts.
    #
    # Weaknesses, opportunities and threats are NOT inferred.
    #

    strengths = []

    if provided_services:
        strengths.append(
            "Services are listed in the provided lead data"
        )

    if provided_products:
        strengths.append(
            "Products are listed in the provided lead data"
        )

    if lead.get("website"):
        strengths.append(
            "A website is listed in the provided lead data"
        )

    if lead.get("rating") is not None:
        strengths.append(
            f"A rating of {lead['rating']} is provided"
        )

    strengths = list(dict.fromkeys(strengths))[:4]

    if not strengths:
        strengths = [NOT_ENOUGH_INFO]

    weaknesses = [NOT_ENOUGH_INFO]

    opportunities = [NOT_ENOUGH_INFO]

    threats = [NOT_ENOUGH_INFO]

    # --------------------------------------------------------
    # IDEAL CUSTOMER PROFILE
    # --------------------------------------------------------

    if target_customers:
        ideal_customer_profile = target_audience
    else:
        ideal_customer_profile = NOT_ENOUGH_INFO

    # --------------------------------------------------------
    # DECISION MAKER
    # --------------------------------------------------------

    #
    # Do not invent a person's name or role.
    #

    decision_maker = NOT_ENOUGH_INFO

    # --------------------------------------------------------
    # SALES OPPORTUNITIES
    # --------------------------------------------------------
    #
    # Do NOT automatically suggest:
    # - SEO
    # - Digital marketing
    # - Advertising
    # - CRM
    # - Website
    # - Social media
    # - Automation
    #
    # unless explicit business information supports the need.
    #

    sales_opportunities = [NOT_ENOUGH_INFO]

    # --------------------------------------------------------
    # PROVIDED FACTS
    # --------------------------------------------------------

    facts = []

    facts.append(
        f"Business name is {name}"
    )

    if lead.get("category"):
        facts.append(
            f"Category is {lead['category']}"
        )

    if lead.get("sub_category"):
        facts.append(
            f"Sub-category is {lead['sub_category']}"
        )

    if lead.get("description") or lead.get("business_description"):
        facts.append(
            "A business description is provided"
        )

    if provided_services:
        facts.append(
            f"{len(provided_services)} services are provided"
        )

    if provided_products:
        facts.append(
            f"{len(provided_products)} products are provided"
        )

    if target_customers:
        facts.append(
            "Target customers are provided"
        )

    if lead.get("website"):
        facts.append(
            f"Website is {lead['website']}"
        )

    if lead.get("rating") is not None:
        facts.append(
            f"Rating is {lead['rating']}"
        )

    if lead.get("review_count") is not None:
        facts.append(
            f"Review count is {lead['review_count']}"
        )

    if lead.get("lead_score") is not None:
        facts.append(
            f"Lead score is {lead['lead_score']}"
        )

    if lead.get("priority"):
        facts.append(
            f"Priority is {lead['priority']}"
        )

    if lead.get("qualification_status"):
        facts.append(
            f"Qualification status is {lead['qualification_status']}"
        )

    provided_facts = facts[:MAX_FACTS]

    # --------------------------------------------------------
    # REASONABLE INFERENCES
    # --------------------------------------------------------
    #
    # Keep this conservative.
    #

    reasonable_inferences = []

    if (
        lead.get("category")
        and lead.get("description")
    ):
        reasonable_inferences.append(
            f"The business operates in the {lead['category']} category "
            "based on the provided classification."
        )

    if provided_services:
        reasonable_inferences.append(
            "The business offers multiple services based on the "
            "provided service list."
        )

    reasonable_inferences = list(
        dict.fromkeys(reasonable_inferences)
    )[:MAX_INFERENCES]

    if not reasonable_inferences:
        reasonable_inferences = [NOT_ENOUGH_INFO]

    # --------------------------------------------------------
    # MISSING INFORMATION
    # --------------------------------------------------------

    missing_information = _missing_information(lead)

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    return {
        "business_summary": business_summary,

        "products_services": grounded_products_services,

        "target_audience": target_audience,

        "pain_points": pain_points,

        "swot": {
            "strengths": strengths,
            "weaknesses": weaknesses,
            "opportunities": opportunities,
            "threats": threats,
        },

        "ideal_customer_profile": ideal_customer_profile,

        "decision_maker_identification": decision_maker,

        "sales_opportunities": sales_opportunities,

        "provided_facts": provided_facts,

        "reasonable_inferences": reasonable_inferences,

        "missing_information": missing_information,
    }


# ============================================================
# PREPARE LEAD FOR LLM
# ============================================================

def prepare_lead_for_llm(lead: dict) -> dict:
    """
    Prepare a compact version of the lead for the LLM.

    The original lead is NOT modified.
    """

    services = lead.get("services") or []
    products = lead.get("products") or []
    target_customers = lead.get("target_customers") or []

    website_analysis = lead.get("website_analysis") or {}
    contacts = lead.get("contacts") or {}
    social_links = lead.get("social_links") or {}

    compact_lead = {

        "lead_id": lead.get("lead_id"),

        "business_name": lead.get("business_name"),

        "category": lead.get("category"),

        "sub_category": lead.get("sub_category"),

        "description": truncate_text(
            lead.get("description")
            or lead.get("business_description"),
            MAX_DESCRIPTION_LENGTH,
        ),

        "services": compact_data(
            services[:MAX_SERVICES_FOR_LLM]
        ),

        "products": compact_data(
            products[:MAX_PRODUCTS_FOR_LLM]
        ),

        "target_customers": compact_data(
            target_customers[:MAX_TARGET_CUSTOMERS_FOR_LLM]
        ),

        "website": lead.get("website"),

        "about_info": truncate_text(
            lead.get("about_info"),
            MAX_ABOUT_LENGTH,
        ),

        "address": lead.get("address"),

        "phone": lead.get("phone"),

        "email": lead.get("email"),

        "rating": lead.get("rating"),

        "review_count": lead.get("review_count"),

        "operating_hours": compact_data(
            lead.get("operating_hours") or {}
        ),

        "website_analysis": compact_data(
            website_analysis
        ),

        "contacts": compact_data(
            contacts
        ),

        "social_links": compact_data(
            social_links
        ),

        "lead_score": lead.get("lead_score"),

        "priority": lead.get("priority"),

        "qualification_status": lead.get(
            "qualification_status"
        ),
    }

    return compact_lead


# ============================================================
# RESEARCH AGENT
# ============================================================

def research_agent(lead: dict) -> dict:
    """
    Analyze ONE business lead and generate structured research.

    The LLM performs analysis, but the final result is grounded
    against the original lead data.
    """

    # --------------------------------------------------------
    # 1. GET ORIGINAL LEAD
    # --------------------------------------------------------

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead must be provided as a dictionary."
        )

    # --------------------------------------------------------
    # 2. COMPACT LEAD
    # --------------------------------------------------------

    lead_for_llm = prepare_lead_for_llm(lead)

    # --------------------------------------------------------
    # 3. JSON INPUT
    # --------------------------------------------------------

    business_information_json = json.dumps(
        lead_for_llm,
        ensure_ascii=False,
        indent=2,
    )

    # --------------------------------------------------------
    # 4. BUILD PROMPT
    # --------------------------------------------------------

    prompt = f"""
You are the Business Research Agent for LeadSutra AI.

Analyze ONE business lead and produce structured business research.

Use STRICT factual grounding.

============================================================
BUSINESS INFORMATION
============================================================

{business_information_json}

============================================================
TASK
============================================================

Generate:

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

============================================================
STRICT FACTUAL GROUNDING
============================================================

1. Use ONLY information provided in BUSINESS INFORMATION.

2. NEVER invent facts.

3. NEVER assume:

- demographics
- income
- revenue
- employees
- business size
- customer behavior
- customer satisfaction
- sales performance
- growth rate
- operational problems
- competitors
- marketing performance

4. Missing information is NOT automatically a problem.

5. Missing information is NOT automatically a weakness.

6. Missing information is NOT automatically a pain point.

7. Do NOT assume the business needs a service simply because
that service is common in its industry.

8. Do NOT automatically recommend:

- website development
- SEO
- digital marketing
- social media marketing
- advertising
- CRM
- automation
- lead generation
- branding

unless the provided information directly supports that need.

9. If a website exists, do NOT claim website development is
needed unless an explicit website problem is provided.

10. If a website does not exist, do NOT automatically claim
poor online presence.

11. Reasonable inferences must directly follow from explicit facts.

12. Do NOT use general industry knowledge as evidence.

13. If information is insufficient, use exactly:

"{NOT_ENOUGH_INFO}"

14. Never invent a person's name.

15. Mention a decision-maker role only when the provided data
supports it.

============================================================
PAIN POINTS
============================================================

A pain point MUST be directly supported by the provided data.

Do NOT invent:

- Low online visibility
- Poor marketing
- Low sales
- Poor customer retention
- Weak branding
- Poor website
- Inefficient operations
- Lack of customers
- Low engagement
- Lack of leads

If no supported pain point exists, return:

["{NOT_ENOUGH_INFO}"]

============================================================
SWOT
============================================================

Every SWOT field must be a JSON array.

STRENGTHS:
Only include strengths directly supported by the input.

WEAKNESSES:
Only include weaknesses explicitly supported by the input.

Missing information is NOT a weakness.

OPPORTUNITIES:
Only include opportunities supported by explicit business
information.

Do NOT create generic industry opportunities.

THREATS:
Only include threats explicitly supported by the input.

Do NOT automatically include:

- competition
- economic conditions
- market saturation
- changing customer preferences

If unsupported, return:

["{NOT_ENOUGH_INFO}"]

============================================================
TARGET AUDIENCE
============================================================

Use ONLY target_customers.

Do NOT invent:

- age
- gender
- income
- occupation
- lifestyle
- demographics

If target_customers is empty:

"{NOT_ENOUGH_INFO}"

============================================================
IDEAL CUSTOMER PROFILE
============================================================

The ICP must be based ONLY on target_customers.

Do not invent demographic or behavioral information.

If target_customers is unavailable:

"{NOT_ENOUGH_INFO}"

============================================================
DECISION MAKER
============================================================

Only identify a decision-maker role when the provided business
information supports it.

Never invent a person's name.

If no decision-maker information is provided:

"{NOT_ENOUGH_INFO}"

============================================================
SALES OPPORTUNITIES
============================================================

A sales opportunity must be directly supported by the business
data.

Do NOT automatically recommend:

- Website development
- SEO
- Digital marketing
- Social media marketing
- CRM
- Automation
- Advertising

If there is no supported opportunity:

["{NOT_ENOUGH_INFO}"]

============================================================
PROVIDED FACTS
============================================================

List only facts explicitly present in BUSINESS INFORMATION.

Do NOT add interpretations.

Maximum: {MAX_FACTS}.

============================================================
REASONABLE INFERENCES
============================================================

Only include conclusions that directly follow from explicit facts.

Do NOT infer:

- The business wants more customers.
- The business has low sales.
- The business needs marketing.
- The business has poor visibility.

If there are no safe inferences:

["{NOT_ENOUGH_INFO}"]

============================================================
MISSING INFORMATION
============================================================

List genuinely missing information.

Do NOT list information that is already present.

Missing information is simply missing information.
It is NOT automatically a business problem.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

Use exactly this structure:

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
    "missing_information": ["string"]
}}
"""

    # --------------------------------------------------------
    # 5. CALL LLM
    # --------------------------------------------------------

    research_text = generate(
        prompt,
        task="research",
    )

    # --------------------------------------------------------
    # 6. PARSE JSON
    # --------------------------------------------------------

    try:

        research_data = json.loads(research_text)

    except json.JSONDecodeError as error:
        logger.warning(
            "Research Agent returned malformed JSON (%s); requesting one schema-preserving repair.",
            error,
        )
        repair_prompt = f"""
Repair the malformed JSON research response below. Return ONLY one valid JSON object.
Preserve every supported fact and conclusion exactly. Do not add, infer, or invent facts.
If a field is absent or cannot be recovered, use "{NOT_ENOUGH_INFO}" for strings or
["{NOT_ENOUGH_INFO}"] for arrays. Ensure every key and value is properly quoted and
the object is complete.

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
{json.dumps(research_text, ensure_ascii=False)}
"""
        try:
            repaired_text = generate(repair_prompt, task="research")
            research_data = json.loads(repaired_text)
        except Exception as repair_error:
            raise ValueError(
                "Research Agent returned invalid JSON and the repair attempt failed: "
                f"{repair_error}"
            ) from repair_error

    # --------------------------------------------------------
    # 7. GROUND + VALIDATE
    # --------------------------------------------------------

    try:

        grounded_data = ground_research_result(
            lead,
            normalize_research_data(research_data),
        )

        research_result = ResearchResult(
            **grounded_data
        )

    except Exception as error:

        raise ValueError(
            f"Research Agent output failed validation: {error}"
        )

    # --------------------------------------------------------
    # Return this agent's result only; callers decide what to do next.
    # --------------------------------------------------------

    return research_result.model_dump()


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    test_lead = {

            "lead_id": "test_001",

            "business_name": "Test Dental Clinic",

            "category": "Dentist",

            "sub_category": "Dental Clinic",

            "description": (
                "A dental clinic providing general dental care."
            ),

            "services": [
                "Dental consultation",
                "Dental treatment",
                "Dental cleaning",
                "Root canal treatment",
                "Dental examination",
            ],

            "products": [],

            "target_customers": [],

            "website": None,

            "about_info": None,

            "address": "Test Address",

            "phone": "1234567890",

            "email": None,

            "rating": 4.5,

            "review_count": 20,

            "operating_hours": {},

            "website_analysis": {},

            "contacts": {},

            "social_links": {},

            "lead_score": 65,

            "priority": "Medium",

            "qualification_status": "Qualified",
    }

    print("\n========================================")
    print("       LEADSUTRA RESEARCH AGENT")
    print("========================================")

    result = research_agent(test_lead)

    print("\n========== STRUCTURED RESEARCH ==========\n")

    print(
        json.dumps(
            result,
            indent=4,
            ensure_ascii=False,
        )
    )
