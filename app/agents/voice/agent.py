"""Local agent metadata; this module never updates the remote agent.

voice.txt contains the conversation instructions. Intent names and intended voice
settings are local metadata, not tool registrations or provider SDK arguments.
Declaring a variable does not populate it or change the dispatch context.
"""

from copy import deepcopy
import json
from pathlib import Path

from app.core.config import get_settings

SUPPORTED_LANGUAGES = ("English (India)", "Hindi", "Marathi")
AGENT_TIMEZONE = "Asia/Kolkata"

OUTBOUND_CALL_PRECONDITIONS = (
    "Verify documented permission or another applicable lawful basis for contact.",
    "Do not dispatch if permission is missing, failed, or inconclusive.",
)

_METADATA = {
    "inbound": {
        "name": "LeadSutra Inbound Assistant",
        "call_type": "Incoming",
        "timezone": "Asia/Kolkata",
        "languages": ["English (India)", "Hindi", "Marathi"],
        "is_welcome_message_dynamic": True,
        "is_welcome_message_interruption": True,
        "is_interruption_allowed": True,
        "transcriber": {"provider": "Soniox"},
        "dynamic_variables": {
            "verified_business_name": "[CONFIGURE_VERIFIED_BUSINESS_NAME]",
            "verified_offering": "[CONFIGURE_VERIFIED_OFFERING]",
            "approved_product_facts": "[CONFIGURE_APPROVED_PRODUCT_FACTS]",
            "approved_pricing": "[CONFIGURE_APPROVED_PRICING_OR_NOT_PROVIDED]",
            "human_transfer_number": "[CONFIGURE_HUMAN_TRANSFER_NUMBER]",
        },
    },
    "outbound": {
        "name": "LeadSutra Outbound Assistant",
        "call_type": "Outgoing",
        "timezone": "Asia/Kolkata",
        "languages": ["English (India)", "Hindi", "Marathi"],
        "is_welcome_message_dynamic": True,
        "is_welcome_message_interruption": True,
        "is_interruption_allowed": True,
        "transcriber": {"provider": "Soniox"},
        "dynamic_variables": {
            "verified_business_name": "[CONFIGURE_VERIFIED_BUSINESS_NAME]",
            "lead_business_name": "[POPULATE_FROM_VALIDATED_LEAD_RECORD]",
            "contact_name": "",
            "business_category": "",
            "business_location": "",
            "business_context": "",
            "proposed_service": "",
            "verified_offering": "[CONFIGURE_VERIFIED_OFFERING]",
            "approved_product_facts": "[CONFIGURE_APPROVED_PRODUCT_FACTS]",
            "approved_pricing": "[CONFIGURE_APPROVED_PRICING_OR_NOT_PROVIDED]",
            "verified_lead_name": "[POPULATE_ONLY_FROM_VERIFIED_LEAD_DATA]",
            "contact_basis_status": "[SET_FROM_PRE_CALL_ELIGIBILITY_CHECK]",
            "human_transfer_number": "[CONFIGURE_HUMAN_TRANSFER_NUMBER]",
        },
    },
}

LEAD_DYNAMIC_VARIABLE_NAMES = (
    "lead_business_name",
    "contact_name",
    "business_category",
    "business_location",
    "business_context",
    "proposed_service",
    "approved_product_facts",
    "approved_pricing",
)

# Conceptual labels referenced by the prompt, not persisted outcomes or tools.
CONVERSATION_INTENTS = (
    "meeting_requested",
    "callback_requested",
    "interested",
    "not_interested",
    "wrong_person",
    "opted_out",
    "needs_human",
    "information_requested",
)

# Conceptual progression only: no active state, transition executor, or LLM loop.
CONVERSATION_STATES = (
    "INITIAL",
    "PERMISSION",
    "DISCOVERY",
    "QUALIFICATION",
    "VALUE_PROPOSITION",
    "OBJECTION_HANDLING",
    "NEXT_STEP",
    "CLOSING",
    "TERMINATED",
)

STATE_INSTRUCTION_SECTIONS = {
    "INITIAL": ("Identity and permission gate",),
    "PERMISSION": ("Permission",),
    "DISCOVERY": ("Discovery",),
    "QUALIFICATION": ("Qualification",),
    "VALUE_PROPOSITION": ("Approved value proposition and factual limits",),
    "OBJECTION_HANDLING": ("Objections and identity questions",),
    "NEXT_STEP": (
        "Interest and conceptual intents",
        "Callback intent",
        "Meeting intent",
        "Information request",
        "Wrong person",
        "Human request",
    ),
    "CLOSING": ("Termination",),
    "TERMINATED": ("Termination",),
}

# Compatibility metadata names; no runtime context/population is introduced.
FUTURE_DYNAMIC_VARIABLE_NAMES = LEAD_DYNAMIC_VARIABLE_NAMES
FUTURE_INTENT_NAMES = CONVERSATION_INTENTS
SUPPORTED_DYNAMIC_VARIABLE_NAMES = tuple(
    _METADATA["outbound"]["dynamic_variables"]
)

INTENDED_VOICE_CONFIGURATION = {
    "status": "configuration to verify",
    "stt": "Soniox",
    "llm": "gpt-4.1-mini",
    "tts_provider": "Cartesia",
    "tts_voice": "Riya",
    "initial_language": "English (India)",
    "tone": "Professional, friendly, natural, concise",
    "speaking_speed": "moderate",
}


def agent_metadata() -> dict:
    settings = get_settings()

    return {
        "agent_id": settings.omnidim_outbound_agent_id,
        "purpose": settings.outbound_call_purpose,
        "role": "LeadSutra AI outbound sales development assistant",
        "remote_configuration_status": "configuration to verify",
        "intended_voice_configuration": deepcopy(INTENDED_VOICE_CONFIGURATION),
        "conversation_intents": list(CONVERSATION_INTENTS),
        "conversation_states": list(CONVERSATION_STATES),
        "state_instruction_sections": deepcopy(STATE_INSTRUCTION_SECTIONS),
        "conversation_control": "conceptual specification only; no local runtime engine",
        "languages": list(SUPPORTED_LANGUAGES),
        "timezone": AGENT_TIMEZONE,
        "supported_dynamic_variables": list(SUPPORTED_DYNAMIC_VARIABLE_NAMES),
        "future_dynamic_variables": list(FUTURE_DYNAMIC_VARIABLE_NAMES),
        "future_intents": list(FUTURE_INTENT_NAMES),
    }


def _agent_config(kind: str) -> dict:
    path = Path(__file__).resolve().with_name("voice.txt")
    instructions = json.loads(path.read_text(encoding="utf-8"))[kind]

    return {
        **deepcopy(_METADATA[kind]),
        **instructions,
    }


def inbound_agent_config() -> dict:
    return _agent_config("inbound")


def outbound_agent_config() -> dict:
    return _agent_config("outbound")