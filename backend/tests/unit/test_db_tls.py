"""MSP_DB_CA_FILE: TLS for MySQL (DO Managed MySQL) and `selector db-grants` users taken from the URLs."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from selector import cli, db
from selector.config import REPO_ROOT, Settings, get_settings

URL = "mysql+pymysql://msp_api:x@db.example:25060/msp"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    for k in ("MSP_DB_CA_FILE", "DATABASE_URL", "INGEST_DATABASE_URL", "MIGRATOR_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _settings(env: pytest.MonkeyPatch, **values: str) -> None:
    for k, v in values.items():
        env.setenv(k, v)
    s = Settings(_env_file=None)
    env.setattr(db, "get_settings", lambda: s)
    env.setattr(cli, "get_settings", lambda: s)


def test_relative_ca_file_is_resolved_from_the_repo_root() -> None:
    s = Settings(_env_file=None, msp_db_ca_file="./cert/do.ca.crt")
    assert s.db_ca_path == REPO_ROOT / "cert" / "do.ca.crt"
    assert Settings(_env_file=None, msp_db_ca_file="/run/msp/do.ca.crt").db_ca_path == Path("/run/msp/do.ca.crt")
    assert Settings(_env_file=None, msp_db_ca_file="").db_ca_path is None


def test_ca_file_turns_on_verified_tls(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ca = tmp_path / "do.ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    _settings(env, MSP_DB_CA_FILE=str(ca))
    assert db.db_connect_args(URL) == {"ssl": {"ca": str(ca)}}  # PyMySQL: CERT_REQUIRED + host-name check
    assert db.db_connect_args(URL + "?ssl_ca=/other.crt") == {}  # the URL's own setting wins


def test_no_ca_file_means_no_tls_args(env: pytest.MonkeyPatch) -> None:
    _settings(env)
    assert db.db_connect_args(URL) == {}


def test_missing_ca_file_stops_with_its_path(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _settings(env, MSP_DB_CA_FILE=str(tmp_path / "missing.crt"))
    with pytest.raises(RuntimeError, match="missing.crt"):
        db.db_connect_args(URL)


def _grants(env: pytest.MonkeyPatch, *argv: str) -> tuple[int, list[tuple[str, str | None, str | None]]]:
    calls: list[tuple[str, str | None, str | None]] = []

    class _Conn:
        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *a: object) -> None:
            pass

    class _Engine:
        def begin(self) -> _Conn:
            return _Conn()

    def apply_grants(conn: object, schema: str, ingest_user: str | None, api_user: str | None) -> int:
        calls.append((schema, ingest_user, api_user))
        return 0

    env.setattr(db, "make_engine", lambda url: _Engine())
    env.setattr("selector.grants.apply_grants", apply_grants)
    args = cli.build_parser().parse_args(["db-grants", *argv])
    return args.func(args), calls


def test_db_grants_uses_the_users_in_the_urls(env: pytest.MonkeyPatch) -> None:
    _settings(
        env,
        DATABASE_URL="mysql+pymysql://app_ro:x@h:25060/prod",
        INGEST_DATABASE_URL="mysql+pymysql://app_load:x@h:25060/prod",
        MIGRATOR_DATABASE_URL="mysql+pymysql://app_ddl:x@h:25060/prod",
    )
    assert _grants(env) == (0, [("prod", "app_load", "app_ro")])


def test_db_grants_with_one_user_for_every_role_grants_nothing(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    one = "mysql+pymysql://tadmin:x@h:25060/msp"
    _settings(env, DATABASE_URL=one, INGEST_DATABASE_URL=one, MIGRATOR_DATABASE_URL=one)
    assert _grants(env) == (0, [])
    assert "no grants needed" in capsys.readouterr().out


def test_db_grants_skips_the_role_that_shares_the_migrator_user(env: pytest.MonkeyPatch) -> None:
    _settings(
        env,
        DATABASE_URL="mysql+pymysql://app_ro:x@h:25060/msp",
        INGEST_DATABASE_URL="mysql+pymysql://tadmin:x@h:25060/msp",
        MIGRATOR_DATABASE_URL="mysql+pymysql://tadmin:x@h:25060/msp",
    )
    assert _grants(env) == (0, [("msp", None, "app_ro")])


def test_grant_statements_skip_a_missing_role() -> None:
    from selector.grants import grant_statements

    assert grant_statements("msp", None, None) == []
    only_ingest = grant_statements("msp", "ing", None)
    assert only_ingest and all("'ing'@" in g for g in only_ingest)
    assert all("'api'@" in g for g in grant_statements("msp", None, "api"))


def test_db_grants_without_grant_right_warns_and_succeeds(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy.exc import OperationalError

    _settings(
        env,
        DATABASE_URL="mysql+pymysql://app_ro:x@h:25060/msp",
        INGEST_DATABASE_URL="mysql+pymysql://app_load:x@h:25060/msp",
        MIGRATOR_DATABASE_URL="mysql+pymysql://tadmin:x@h:25060/msp",
    )

    def denied(conn: object, schema: str, ingest_user: str | None, api_user: str | None) -> int:
        raise OperationalError("GRANT", {}, Exception(1044, "Access denied for user 'tadmin'@'%'"))

    _grants(env)  # installs the engine stub
    env.setattr("selector.grants.apply_grants", denied)
    args = cli.build_parser().parse_args(["db-grants"])
    assert args.func(args) == 0
    assert "WARNING" in capsys.readouterr().err
