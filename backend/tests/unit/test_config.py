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
    monkeypatch.setenv("DEFAULT_SESSION_MODE", "nosave")
    monkeypatch.setenv("EPHEMERAL_IDLE_MINUTES", "5")
    s = Settings()
    assert s.default_session_mode == "nosave"
    assert s.ephemeral_idle_minutes == 5


@pytest.mark.parametrize("value", ["saved", "SAVED", " saved ", "forever"])
def test_ns1_default_session_mode_other_than_nosave_stops_start_up(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """NS1 (DESIGN v0.5 B2.5): Saved can be offered but never defaulted; the error names the rule."""
    monkeypatch.setenv("DEFAULT_SESSION_MODE", value)
    with pytest.raises(ValidationError, match=r"DEFAULT_SESSION_MODE must be nosave \(DESIGN v0\.5 B2\)"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_ns1_saved_in_env_file_is_refused(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("DEFAULT_SESSION_MODE=saved\n")
    with pytest.raises(ValidationError, match="DESIGN v0.5 B2"):
        Settings(_env_file=env)  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["nosave", "NoSave", ""])
def test_ns1_nosave_or_blank_means_nosave(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DEFAULT_SESSION_MODE", value)
    assert Settings(_env_file=None).default_session_mode == "nosave"  # type: ignore[call-arg]


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


def _compose_env_file(path: Path) -> dict[str, str]:
    """Parse an env file the way Docker Compose `env_file:` does for our purposes.

    Compose does not strip a trailing `# comment` after a blank value (`KEY=   # note` becomes "# note"), so this
    parser deliberately keeps everything after the first `=` (QA issue 1).
    """
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "=" in line, f"not KEY=VALUE: {raw!r}"
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def test_env_example_has_no_inline_comments() -> None:
    """QA issue 1: every comment in .env.example is on its own line, so compose passes clean values."""
    from selector.config import REPO_ROOT

    env = _compose_env_file(REPO_ROOT / ".env.example")
    assert env, ".env.example parsed to nothing"
    leaked = {k: v for k, v in env.items() if "#" in v}
    assert not leaked, f"inline comments would leak into values: {sorted(leaked)}"


def test_env_example_loads_the_compose_way(monkeypatch: pytest.MonkeyPatch) -> None:
    from selector.config import REPO_ROOT

    for key, value in _compose_env_file(REPO_ROOT / ".env.example").items():
        monkeypatch.setenv(key, value)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.llm_price_in_per_mtok_usd == 0.0
    assert s.llm_provider == "fake"


def test_leaked_comment_counts_as_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Older .env copies made from the previous .env.example must still start (QA issue 1)."""
    monkeypatch.setenv("LLM_PRICE_IN_PER_MTOK_USD", "# USD per million input tokens")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "# used on 5xx/timeout")
    monkeypatch.setenv("LLM_MODEL", "  # pinned model id")
    monkeypatch.setenv("HUD_API_TOKEN", "# optional")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.llm_price_in_per_mtok_usd == 0.0
    assert s.llm_fallback_provider == ""
    assert s.llm_model == ""
    assert not s.hud_api_token.get_secret_value()
