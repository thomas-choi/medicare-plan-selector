"""Runtime settings, read from the environment (server `.env`). See `.env.example` for every key."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SessionMode = Literal["nosave", "saved"]
# DESIGN v0.5 B2 (NS-REQ): every new session starts in No-save. Saved may be offered, never defaulted, so the only
# accepted value of DEFAULT_SESSION_MODE is "nosave"; anything else stops the API at start-up.
DefaultSessionMode = Literal["nosave"]
DEFAULT_SESSION_MODE_ERROR = "DEFAULT_SESSION_MODE must be nosave (DESIGN v0.5 B2)"
# `xai` is the `openai_compat` adapter with xAI's base URL and key (see selector/agent/providers).
LLMProvider = Literal["anthropic", "openai", "openai_compat", "xai", "ollama", "fake", ""]

REPO_ROOT = Path(__file__).resolve().parents[2]


def default_env_files() -> tuple[Path, ...]:
    """Where `.env` is read from, lowest priority first.

    1. `<repo>/.env` (the file `cp .env.example .env` creates), so host commands work from any directory;
    2. `./.env` in the current directory (backward compatible with running from `backend/`);
    3. `$MSP_ENV_FILE` if set (explicit path, highest priority).
    Real environment variables always win over every file. Inside the image `/app` has no `.env`; compose passes
    the values as environment variables instead.
    """
    files = [REPO_ROOT / ".env", Path.cwd() / ".env"]
    if explicit := os.environ.get("MSP_ENV_FILE"):
        files.append(Path(explicit))
    seen: list[Path] = []
    for f in files:
        if f.resolve() not in [x.resolve() for x in seen]:
            seen.append(f)
    return tuple(seen)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=default_env_files(), env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _blank_means_default(cls, data: Any) -> Any:
        """`KEY=` (blank) in `.env` means "use the default", for every non-string setting.

        `.env.example` ships blank placeholders such as `LLM_PRICE_IN_PER_MTOK_USD=`; without this a blank number
        made `Settings()` fail to load. A value that starts with `#` is a leaked inline comment and counts as blank.
        """
        if isinstance(data, dict):
            str_fields = {n for n, f in cls.model_fields.items() if f.annotation is str}
            out: dict[str, Any] = {}
            for k, v in data.items():
                if isinstance(v, str) and v.strip().startswith("#"):
                    # Docker Compose `env_file` keeps a trailing comment after a blank value
                    # (`KEY=   # note` -> "# note"); no real setting value starts with '#'.
                    v = ""
                if isinstance(v, str) and not v.strip() and k.lower() not in str_fields:
                    continue
                out[k] = v
            return out
        return data

    @field_validator("default_session_mode", mode="before")
    @classmethod
    def _default_mode_is_nosave(cls, v: Any) -> Any:
        """G1 (DESIGN v0.5 B2.3): refuse `saved` (or any other value) with an error that names the rule."""
        if isinstance(v, str) and v.strip().lower() != "nosave":
            raise ValueError(DEFAULT_SESSION_MODE_ERROR)
        return v.strip().lower() if isinstance(v, str) else v

    # Databases. Three roles: migrator (DDL), ingest (plan tables RW), api (plan RO, user tables RW).
    database_url: str = "mysql+pymysql://msp_api:dev-api-pw@127.0.0.1:3307/msp"  # dev stack (host side)
    ingest_database_url: str = ""
    migrator_database_url: str = ""
    redis_url: str = "redis://:dev-redis-pw@127.0.0.1:6380/0"

    # Sessions and privacy (DESIGN §8.1, §8.5).
    default_session_mode: DefaultSessionMode = "nosave"
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
    xai_api_key: SecretStr = SecretStr("")
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
    # Optional pepper for the per-IP quota key. The key is already HMAC(daily random salt in Redis, IP prefix);
    # blank is fine.
    ip_hash_secret: SecretStr = SecretStr("")

    # External lookups.
    hud_api_token: SecretStr = SecretStr("")
    hud_api_base: str = "https://www.huduser.gov/hudapi/public/usps"

    # Doctor listing checks (design v0.4 addendum A3): public provider directories and the CMS opt-out list (S14).
    # The compare request waits at most `directory_budget_s` for them; anything slower shows "can't check".
    directory_budget_s: float = Field(default=8.0, ge=0.5, le=30)
    directory_min_interval_s: float = Field(default=1.0, ge=0, le=10)  # per carrier host
    optout_url: str = "https://data.cms.gov/data-api/v1/dataset/cc4e7ff6-9433-4765-b073-8bf1ce09093b/data"
    optout_vintage: str = "Opt Out Affidavits 2026-09-01"

    # Admin API (DESIGN §7, Q2). nginx does basic auth + IP allowlist and then adds the header
    # `X-Admin-Gate: <ADMIN_GATE_SECRET>`; the API refuses admin calls without it. Blank = admin API off.
    admin_gate_secret: SecretStr = SecretStr("")

    # Data.
    plan_year: int = 2027
    data_dir: str = "data"
    app_version: str = "dev"

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
