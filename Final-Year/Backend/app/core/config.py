from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    api_version: str = "v1"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    mongodb_uri: SecretStr | None = None
    mongodb_database: str = Field(default="leadsutra", min_length=1)
    mongodb_server_selection_timeout_ms: int = Field(default=5000, ge=250, le=60000)
    auth_jwt_secret: SecretStr | None = None
    auth_cookie_secure: bool = False
    auth_cookie_name: str = "leadsutra_session"
    log_file_path: str = str(_BACKEND / "logs" / "backend.log")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    omnidim_api_key: str | None = None
    omnidim_outbound_agent_id: int | None = 261506
    outbound_calls_enabled: bool = False
    outbound_call_purpose: str = "commercial_sales_call"
    outbound_represented_business_name: str | None = None
    outbound_represented_business_identity_verified: bool = False
    lead_json_path: str = str(_BACKEND / "app/results/leads")
    eligibility_db_path: str = str(_BACKEND / "app/results/calls/calling_eligibility.sqlite3")
    proposal_root: str = str(_BACKEND / "app/results/proposals")
    research_root: str = str(_BACKEND / "app/results/research")
    eligibility_admin_token: str | None = None
    eligibility_reviewer_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=_BACKEND / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class EmailSettings(Settings):
    """Reuse settings sources without making SMTP validation affect Voice."""

    email_sending_enabled: bool = False
    email_db_path: str = str(_BACKEND / "app/results/emails/emails.sqlite3")
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: str | None = None
    smtp_timeout_seconds: float = Field(default=15, gt=0, le=120)
    outreach_company_name: str = "LeadSutra AI"
    outreach_company_summary: str = (
        "We help businesses improve lead generation, customer engagement, "
        "and follow-up processes using AI-powered solutions and automation."
    )
    outreach_service_offerings: str = (
        "Enriching lead records with relevant business and contact details; "
        "Prioritizing leads to support outreach planning; "
        "Organizing inquiries and follow-up activities; "
        "Automating routine follow-ups and customer engagement"
    )
    outreach_contact_name: str | None = None
    outreach_email_signature: str = "LeadSutra AI Team"
    outreach_email_tagline: str = (
        "Helping businesses grow through AI, automation, and smarter customer engagement."
    )
    outreach_website_url: str | None = None
    outreach_intro_call_minutes: int = Field(default=15, ge=5, le=60)
    outreach_email_template: str = """Dear {{business_name}} Team,

I hope you're doing well.

My name is {{sender_name}}, and I'm reaching out on behalf of {{company_name}}. I came across {{business_name}} and wanted to introduce our services and explore whether we could help your business improve its customer acquisition, lead management, and overall operational efficiency.

At {{company_name}}, we focus on AI-powered solutions, intelligent automation, and streamlined workflows to reduce repetitive tasks, improve customer engagement, and identify opportunities for growth.

Based on your business type and goals, we could explore solutions such as:
- Lead Generation: Attract and identify potential customers who may be interested in your products or services.
- Automated Follow-Ups: Help ensure enquiries and prospective customers receive timely follow-ups.
- Customer Engagement: Streamline communication with prospects and existing customers.
- Workflow Automation: Reduce repetitive manual tasks and improve day-to-day efficiency.
- Business-Specific AI Solutions: Identify opportunities to use AI and automation for your business challenges.

Rather than offering a one-size-fits-all solution, explain that we first want to understand their current processes, challenges, and growth objectives before recommending an approach that fits.

Invite a brief {{intro_call_minutes}}-{{intro_call_minutes_plus_five}} minute introductory conversation to learn about their priorities and discuss potential ways {{company_name}} could add value.

Ask whether they are available for a short conversation this week. If they are not the appropriate contact, ask to be directed to the relevant person. Thank them for their time.

Best regards,
{{sender_name}}
Email: {{sender_email}}
Website: {{website_url}}

If they prefer not to receive further messages, say they can let us know and we will update our records.

Use this as the dedicated structure and content guide, not fixed copy. Write polished, fresh wording tailored using verified lead facts and research. Never leave template placeholders in the finished email. Omit optional contact or website lines when no value is configured."""


class DiscoverySettings(BaseSettings):
    """Discovery configuration, isolated from Voice and SMTP validation."""

    model_config = Settings.model_config

    google_places_api_key: SecretStr | None = None
    google_maps_api_key: SecretStr | None = None
    leadsutra_enable_google_places: bool = True
    leadsutra_enable_maps_browser: bool = True
    leadsutra_enable_maps_browser_fallback: bool = False
    leadsutra_maps_fallback_on_zero_results: bool = False
    leadsutra_places_max_attempts: int = Field(default=2, ge=1)
    leadsutra_places_timeout_seconds: float = Field(default=15, gt=0)
    leadsutra_places_retry_delay_seconds: float = Field(default=0.15, ge=0)
    leadsutra_competitor_radius_meters: int = Field(default=10000, ge=500, le=50000)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_email_settings() -> EmailSettings:
    return EmailSettings()
