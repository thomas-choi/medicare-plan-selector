from __future__ import annotations

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
