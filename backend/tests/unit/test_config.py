from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from selector.config import Settings


def test_defaults_match_accepted_open_questions() -> None:
    s = Settings()
    assert s.default_session_mode == "nosave"  # Q10
    assert s.ephemeral_idle_minutes == 30  # Q11
    assert s.ephemeral_max_hours == 4  # Q11
    assert s.ephemeral_end_grace_seconds == 60  # Thomas approval note 2
    assert s.retention_days == 30  # Q4
    assert s.feedback_retention_days == 365  # Q4
    assert s.llm_daily_budget_usd == 10.0  # Q3
    assert s.max_turns_per_session == 40  # Q3
    assert s.max_sessions_per_ip_per_day == 5  # Q3
    assert s.captcha_provider == "none"  # Q7
    assert (s.max_message_chars, s.max_drugs, s.max_providers) == (2000, 30, 15)


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_SESSION_MODE", "saved")
    monkeypatch.setenv("EPHEMERAL_IDLE_MINUTES", "5")
    s = Settings()
    assert s.default_session_mode == "saved"
    assert s.ephemeral_idle_minutes == 5


def test_rejects_unknown_session_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_SESSION_MODE", "forever")
    with pytest.raises(ValidationError):
        Settings()


def test_secrets_are_not_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    s = Settings()
    assert "sk-test-not-real" not in repr(s)
    assert s.anthropic_api_key.get_secret_value() == "sk-test-not-real"


def test_role_urls_fall_back() -> None:
    s = Settings(database_url="mysql+pymysql://a@h/db")
    assert s.effective_ingest_url == s.database_url
    assert s.effective_migrator_url == s.database_url


def test_blank_numbers_mean_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """README finding: `LLM_PRICE_*=` (blank, as in .env.example) must not break Settings()."""
    monkeypatch.setenv("LLM_PRICE_IN_PER_MTOK_USD", "")
    monkeypatch.setenv("LLM_PRICE_OUT_PER_MTOK_USD", "  ")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "")
    monkeypatch.setenv("COOKIE_SECURE", "")
    monkeypatch.setenv("LLM_PROVIDER", "")
    s = Settings()
    assert s.llm_price_in_per_mtok_usd == 0.0
    assert s.llm_price_out_per_mtok_usd == 0.0
    assert s.llm_daily_budget_usd == 10.0
    assert s.cookie_secure is True
    assert s.llm_provider == ""


def test_blank_values_in_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LLM_PRICE_IN_PER_MTOK_USD=\nLLM_PRICE_OUT_PER_MTOK_USD=3\nMAX_TURNS_PER_SESSION=\n")
    s = Settings(_env_file=env)  # type: ignore[call-arg]
    assert s.llm_price_in_per_mtok_usd == 0.0
    assert s.llm_price_out_per_mtok_usd == 3.0
    assert s.max_turns_per_session == 40


def test_env_file_locations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The repo-root .env is found from any directory; MSP_ENV_FILE wins over both."""
    from selector.config import REPO_ROOT, default_env_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MSP_ENV_FILE", raising=False)
    files = default_env_files()
    assert files[0] == REPO_ROOT / ".env"
    assert files[-1] == tmp_path / ".env"
    monkeypatch.setenv("MSP_ENV_FILE", str(tmp_path / "custom.env"))
    assert default_env_files()[-1] == tmp_path / "custom.env"


def test_host_defaults_use_published_ports() -> None:
    """Host-side defaults point at the compose ports on 127.0.0.1 (3307 MySQL, 6380 Redis)."""
    s = Settings()
    assert "127.0.0.1:3307" in s.database_url
    assert "127.0.0.1:6380" in s.redis_url


def test_xai_is_a_known_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "xai")
    assert Settings().llm_provider == "xai"
