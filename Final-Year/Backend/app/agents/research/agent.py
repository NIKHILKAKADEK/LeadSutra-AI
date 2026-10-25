import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from app.llm.provider import generate, generate_with_gemini_google_search
from app.agents.research.schema import ResearchResult
from app.agents.research.prompt import (
    build_research_prompt,
)

logger = logging.getLogger(__name__)


NOT_ENOUGH_INFO = "Not enough information to determine from provided data"

# Output limits
MAX_SERVICES_IN_OUTPUT = 15
MAX_FACTS = 16
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

# NORMALIZATION

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


# HELPER FUNCTIONS

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



# MISSING INFORMATION


def _missing_information(lead: dict) -> list[str]:
    """
    Determine genuinely missing information from the original lead.
    """

    fields = (
        ("products", "Products"),
        ("target_customers", "Target customers"),
        ("services", "Services"),
        ("website", "Website"),
        ("address", "Address"),
        ("category", "Business category"),
        ("email", "Email address"),
        ("phone", "Phone number"),
        ("review_count", "Review count"),
        ("rating", "Public rating"),
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

    contacts = lead.get("contacts") if isinstance(lead.get("contacts"), dict) else {}
    contact_person = contacts.get("contact_person")
    if isinstance(contact_person, dict):
        contact_person = contact_person.get("value")
    if not (isinstance(contact_person, str) and contact_person.strip()):
        missing.append("Named business contact and decision-maker role")

    return missing[:MAX_MISSING_INFORMATION] or [NOT_ENOUGH_INFO]



def _clean_offerings(value: Any, maximum: int) -> list[str]:
    items = value if isinstance(value, list) else []
    excluded = {
        "why are we different",
        "why choose us",
        "what do we do",
        "design & developed by brand beavers",
        "design and developed by brand beavers",
        "design & developed by",
        "contact us",
        "learn more",
    }
    cleaned = []
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip()
        normalized = text.casefold().strip(" .,:;!?-")
        if (
            not text
            or normalized in excluded
            or re.search(r"\b(?:design(?:ed)?\s*(?:&|and)\s*developed by|website by|powered by)\b", normalized)
        ):
            continue
        cleaned.append(text)
    return list(dict.fromkeys(cleaned))[:maximum]


# GROUND RESEARCH RESULT


def ground_research_result(lead: dict, data: dict) -> dict:
    """
    Build the final research result.

    IMPORTANT:
    The LLM is used for analysis, but unsupported claims are not
    trusted automatically.

    Deterministic lead data is preferred whenever possible.
    """

    name = lead.get("business_name") or "This business"

    # BUSINESS SUMMARY

    description = truncate_text(
        lead.get("description")
        or lead.get("business_description"),
        300,
    )

    category = lead.get("category") or lead.get("sub_category")
    address = lead.get("address")
    provided_services = _clean_offerings(lead.get("services"), MAX_SERVICES_IN_OUTPUT)
    provided_products = _clean_offerings(lead.get("products"), MAX_SERVICES_IN_OUTPUT)
    summary_parts = [description] if description else []
    about_info = truncate_text(lead.get("about_info"), 500)
    if about_info and about_info.casefold() != (description or "").casefold():
        summary_parts.append("Website profile: " + about_info)
    if category:
        summary_parts.append(f"Category: {category}")
    if address:
        summary_parts.append(f"Location: {address}")
    if provided_services:
        summary_parts.append("Listed services: " + ", ".join(provided_services[:5]))
    if provided_products:
        summary_parts.append("Listed products: " + ", ".join(provided_products[:5]))
    if lead.get("rating") is not None:
        rating_fact = f"Public listing rating: {lead['rating']}/5"
        if lead.get("review_count") is not None:
            rating_fact += f" from {lead['review_count']} reviews"
        summary_parts.append(rating_fact)
    business_summary = (
        f"{name}: " + "; ".join(summary_parts)
        if summary_parts
        else f"{name} is listed in the lead database, but no further business details were returned."
    )

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

    # TARGET AUDIENCE

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
        target_audience = (
            f"Potential customers seeking {str(category).strip().lower()} services "
            "(an inference from the public category, not confirmed by the business)."
            if category else NOT_ENOUGH_INFO
        )

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
        strengths.append("Listed services: " + ", ".join(provided_services[:3]))

    if provided_products:
        strengths.append("Listed products: " + ", ".join(provided_products[:3]))

    if lead.get("website"):
        strengths.append(f"Website is listed: {lead['website']}")

    if lead.get("rating") is not None:
        rating_strength = f"Public listing shows a {lead['rating']}/5 rating"
        if lead.get("review_count") is not None:
            rating_strength += f" across {lead['review_count']} reviews"
        strengths.append(rating_strength)

    if lead.get("phone") or lead.get("email"):
        strengths.append("Public listing includes contact details")

    strengths = list(dict.fromkeys(strengths))[:4]

    if not strengths:
        strengths = [NOT_ENOUGH_INFO]

    weaknesses = [NOT_ENOUGH_INFO]

    opportunities = (
        [
            "Create service-specific outreach around the listed offerings: "
            + ", ".join(provided_services[:3])
        ]
        if provided_services
        else [NOT_ENOUGH_INFO]
    )

    threats = [NOT_ENOUGH_INFO]

    # --------------------------------------------------------
    # IDEAL CUSTOMER PROFILE
    # --------------------------------------------------------

    if target_customers or (category and target_audience != NOT_ENOUGH_INFO):
        ideal_customer_profile = target_audience
    else:
        ideal_customer_profile = NOT_ENOUGH_INFO

    # --------------------------------------------------------
    # DECISION MAKER
    # --------------------------------------------------------

    #
    # Do not invent a person's name or role.
    #

    contacts = lead.get("contacts") if isinstance(lead.get("contacts"), dict) else {}
    contact_person = contacts.get("contact_person")
    if isinstance(contact_person, dict):
        contact_person = contact_person.get("value")
    decision_maker = (
        f"{contact_person} is listed as a business contact; their decision-making role was not provided."
        if isinstance(contact_person, str) and contact_person.strip()
        else NOT_ENOUGH_INFO
    )

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

    sales_opportunities = (
        [
            "Reference the business's listed services in tailored outreach: "
            + ", ".join(provided_services[:3])
        ]
        if provided_services
        else [NOT_ENOUGH_INFO]
    )

    # --------------------------------------------------------
    # PROVIDED FACTS
    # --------------------------------------------------------

    facts = []

    facts.append(
        f"Business name is {name}"
    )

    if category:
        facts.append(f"Category is {category}")

    if lead.get("sub_category"):
        facts.append(
            f"Sub-category is {lead['sub_category']}"
        )

    if description:
        facts.append(f"Business description: {description}")

    if about_info and about_info.casefold() != (description or "").casefold():
        facts.append(f"Official website profile: {about_info}")

    if provided_services:
        facts.append(f"Listed services: {', '.join(provided_services[:5])}")

    if provided_products:
        facts.append(f"Listed products: {', '.join(provided_products[:5])}")

    if target_customers:
        facts.append(
            "Target customers are provided"
        )

    if lead.get("website"):
        facts.append(f"Website is {lead['website']}")

    if address:
        facts.append(f"Address is {address}")

    if lead.get("phone"):
        facts.append(f"Phone number is {lead['phone']}")

    if lead.get("email"):
        facts.append(f"Email address is {lead['email']}")

    if lead.get("rating") is not None:
        facts.append(
            f"Rating is {lead['rating']}"
        )

    if lead.get("review_count") is not None:
        facts.append(
            f"Review count is {lead['review_count']}"
        )

    hours = lead.get("operating_hours") or []
    if isinstance(hours, list):
        facts.extend(
            f"Published operating hours: {item.get('day')} {item.get('opens') or ''}–{item.get('closes') or 'closed'}"
            for item in hours if isinstance(item, dict) and item.get("day")
        )

    if isinstance(contact_person, str) and contact_person.strip():
        facts.append(f"Listed business contact is {contact_person}")

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

    if category and address:
        reasonable_inferences.append(
            f"The business is listed in the {category} category at {address}."
        )

    if category and not target_customers:
        reasonable_inferences.append(
            f"Potential customers may be people seeking {str(category).strip().lower()} services; "
            "this is inferred from the listing category and is not verified."
        )

    if provided_services:
        reasonable_inferences.append(
            f"The business promotes {len(provided_services)} listed services."
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

    research_sources = [
        item for item in lead.get("research_sources", [])
        if isinstance(item, dict) and isinstance(item.get("url"), str)
        and item["url"].startswith(("https://", "http://"))
    ][:20]
    known_source_urls = {item["url"].rstrip("/ ") for item in research_sources}
    web_findings = []
    for item in data.get("web_findings", []):
        if not isinstance(item, str) or not item.strip():
            continue
        cited_urls = re.findall(r"\[Source:\s*(https?://[^\]\s]+)\]", item, flags=re.I)
        if cited_urls and all(url.rstrip("/ .,)") in known_source_urls for url in cited_urls):
            web_findings.append(item.strip())

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
        "web_findings": web_findings[:12],
        "research_sources": research_sources,
        "contact_page_url": lead.get("contact_page_url"),
        "about_page_url": lead.get("about_page_url"),
        "operating_hours": lead.get("operating_hours", []) if isinstance(lead.get("operating_hours"), list) else [],
        "researched_at": datetime.now(timezone.utc).isoformat(),
    }



# PREPARE LEAD FOR LLM


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

        "website_research_pages": compact_data(
            lead.get("website_research_pages", [])[:6]
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



# RESEARCH AGENT


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

    google_search_enabled = os.getenv("GEMINI_RESEARCH_GOOGLE_SEARCH", "true").strip().casefold() in {"1", "true", "yes", "on"}
    has_gemini_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    prompt = build_research_prompt(business_information_json, MAX_FACTS, google_search=google_search_enabled and has_gemini_key)

    # --------------------------------------------------------
    # 5. CALL LLM
    # --------------------------------------------------------

    google_sources: list[dict[str, str]] = []
    if google_search_enabled and has_gemini_key:
        research_text, google_sources = generate_with_gemini_google_search(prompt)
    else:
        if google_search_enabled:
            logger.info("Google Search grounding is unavailable; configure GEMINI_API_KEY to enable it.")
        research_text = generate(prompt, task="research")

    # --------------------------------------------------------
    # 6. PARSE JSON
    # --------------------------------------------------------

    try:
        research_data = json.loads(research_text)
        if not isinstance(research_data, dict):
            logger.warning(
                "Research Agent returned JSON of type %s; using grounded lead data.",
                type(research_data).__name__,
            )
            research_data = {}
    except (json.JSONDecodeError, TypeError) as error:
        logger.warning(
            "Research Agent returned malformed JSON (%s); using grounded lead data without a repair call.",
            error,
        )
        research_data = {}

    # --------------------------------------------------------
    # 7. GROUND + VALIDATE
    # --------------------------------------------------------

    try:

        lead_with_sources = dict(lead)
        lead_with_sources["research_sources"] = list(lead.get("research_sources", [])) + google_sources
        grounded_data = ground_research_result(
            lead_with_sources,
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

    return research_result.model_dump(mode="json")



# DIRECT TEST


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
