"""Environment-based application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional .env file."""

    app_name: str = "LeadSutra AI Backend"
    environment: str = "development"
    api_version: str = "v1"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]
    omnidim_api_key: str | None = None
    omnidim_outbound_agent_id: int | None = 261506
    outbound_calls_enabled: bool = False
    outbound_call_purpose: str = "commercial_sales_call"
    outbound_represented_business_name: str | None = None
    outbound_represented_business_identity_verified: bool = False
    lead_json_path: str = r"D:\Leadsutra_AI\leads.json"
    eligibility_db_path: str = "data/calling_eligibility.sqlite3"
    eligibility_admin_token: str | None = None
    eligibility_reviewer_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
