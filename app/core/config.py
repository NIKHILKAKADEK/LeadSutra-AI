"""Backend settings using the existing environment/.env mechanism."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    api_version: str = "v1"
    omnidim_api_key: str | None = None
    omnidim_outbound_agent_id: int | None = 261506
    outbound_calls_enabled: bool = False
    outbound_call_purpose: str = "commercial_sales_call"
    outbound_represented_business_name: str | None = None
    outbound_represented_business_identity_verified: bool = False
    lead_json_path: str = str(_BACKEND / "app/results/leads")
    eligibility_db_path: str = str(_BACKEND / "app/results/calls/calling_eligibility.sqlite3")
    proposal_root: str = str(_BACKEND / "app/results/proposals")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_email_settings() -> EmailSettings:
    return EmailSettings()
