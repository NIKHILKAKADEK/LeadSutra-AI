"""Tests for reusable multilingual voice-agent configuration payloads."""

from app.services.voice_agent_configs import (
    AGENT_TIMEZONE,
    OUTBOUND_CALL_PRECONDITIONS,
    SUPPORTED_LANGUAGES,
    inbound_agent_config,
    outbound_agent_config,
)


def test_inbound_agent_configuration() -> None:
    config = inbound_agent_config()

    assert config["name"] == "LeadSutra Inbound Assistant"
    assert config["call_type"] == "Incoming"
    assert config["transcriber"] == {"provider": "Soniox"}
    prompt = " ".join(section["body"] for section in config["context_breakdown"])
    assert "AI assistant" in prompt
    assert "Never invent" in prompt
    assert "Respect any request to stop" in prompt
    assert "human" in prompt.lower()


def test_outbound_agent_configuration_and_safety() -> None:
    config = outbound_agent_config()

    assert config["name"] == "LeadSutra Outbound Assistant"
    assert config["call_type"] == "Outgoing"
    prompt = " ".join(section["body"] for section in config["context_breakdown"])
    assert "lawful basis" in prompt
    assert "opt-out" in prompt
    assert "Never continue after a clear refusal" in prompt
    assert "Never pressure" in prompt
    assert "Never claim to represent a business" in prompt
    assert "lead_business_name" in config["dynamic_variables"]
    assert "[CONFIGURE_VERIFIED_OFFERING]" in config["dynamic_variables"]["verified_offering"]
    assert "[CONFIGURE_APPROVED_PRICING_OR_NOT_PROVIDED]" in config["dynamic_variables"]["approved_pricing"]
    assert OUTBOUND_CALL_PRECONDITIONS


def test_both_configurations_use_verified_languages_timezone_and_dynamic_greetings() -> None:
    for config in (inbound_agent_config(), outbound_agent_config()):
        assert config["languages"] == list(SUPPORTED_LANGUAGES)
        assert config["languages"] == ["English (India)", "Hindi", "Marathi"]
        assert config["timezone"] == AGENT_TIMEZONE == "Asia/Kolkata"
        assert config["is_welcome_message_dynamic"] is True
        assert config["is_welcome_message_interruption"] is True
        assert "voice" not in config


def test_configurations_return_independent_payloads() -> None:
    first = inbound_agent_config()
    first["languages"].append("unconfigured")

    assert inbound_agent_config()["languages"] == list(SUPPORTED_LANGUAGES)
