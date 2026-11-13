"""Runtime settings, read from the environment (server `.env`). See `.env.example` for every key."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SessionMode = Literal["nosave", "saved"]
LLMProvider = Literal["anthropic", "openai", "openai_compat", "ollama", "fake", ""]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Databases. Three roles: migrator (DDL), ingest (plan tables RW), api (plan RO, user tables RW).
    database_url: str = "mysql+pymysql://msp_api:msp_api@127.0.0.1:3307/msp"
    ingest_database_url: str = ""
    migrator_database_url: str = ""
    redis_url: str = "redis://:msp_redis@127.0.0.1:6380/0"

    # Sessions and privacy (DESIGN §8.1, §8.5).
    default_session_mode: SessionMode = "nosave"
    retention_days: int = Field(default=30, ge=1)
    feedback_retention_days: int = Field(default=365, ge=1)
    ephemeral_idle_minutes: int = Field(default=30, ge=1)
    ephemeral_max_hours: int = Field(default=4, ge=1)
    ephemeral_end_grace_seconds: int = Field(default=60, ge=0)
    profile_enc_key: SecretStr = SecretStr("")
    profile_key_version: int = 1
    cookie_secure: bool = True

    # LLM provider (DESIGN §6.4).
    llm_provider: LLMProvider = ""
    llm_model: str = ""
    llm_base_url: str = ""
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_compat_api_key: SecretStr = SecretStr("")
    llm_fallback_provider: LLMProvider = ""
    llm_fallback_model: str = ""
    llm_timeout_s: float = 60
    llm_max_output_tokens: int = 1500
    llm_temperature: float = 0.2
    llm_price_in_per_mtok_usd: float = 0.0
    llm_price_out_per_mtok_usd: float = 0.0

    # Quotas and abuse controls (DESIGN §8.2, OPEN-QUESTIONS Q3).
    llm_daily_budget_usd: float = 10.0
    max_turns_per_session: int = 40
    max_tokens_per_session: int = 200_000
    max_sessions_per_ip_per_day: int = 5
    max_message_chars: int = 2000
    max_drugs: int = 30
    max_providers: int = 15
    captcha_provider: Literal["none", "turnstile", "hcaptcha"] = "none"

    # External lookups.
    hud_api_token: SecretStr = SecretStr("")
    hud_api_base: str = "https://www.huduser.gov/hudapi/public/usps"

    # Data.
    plan_year: int = 2027
    data_dir: str = "data"

    @field_validator("database_url", "redis_url")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("must be set")
        return v

    @property
    def effective_ingest_url(self) -> str:
        return self.ingest_database_url or self.database_url

    @property
    def effective_migrator_url(self) -> str:
        return self.migrator_database_url or self.effective_ingest_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
