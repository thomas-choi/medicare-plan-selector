"""QA #6: an empty or missing schema must make the API loudly not-ready, not silently "unavailable"."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from tests.api_support import client
from tests.conftest import MIGRATOR_URL

pytestmark = pytest.mark.infra


@pytest.fixture(scope="module")
def empty_db() -> Iterator[dict[str, str]]:
    """A migrated database with grants but no plan data (what an app restart on tmpfs MySQL + migrate leaves)."""
    from alembic.config import Config

    from alembic import command
    from selector.cli import BACKEND_DIR
    from selector.grants import apply_grants

    name = f"msp_test_empty_{uuid.uuid4().hex[:6]}"
    admin = create_engine(MIGRATOR_URL)
    with admin.begin() as c:
        c.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    url = MIGRATOR_URL.rsplit("/", 1)[0] + "/" + name
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    with admin.begin() as c:
        apply_grants(c, name, "msp_ingest", "msp_api")

    def u(role_url: str) -> str:
        return role_url.rsplit("/", 1)[0] + "/" + name

    from tests.conftest import API_URL, INGEST_URL

    try:
        yield {"name": name, "migrator": url, "ingest": u(INGEST_URL), "api": u(API_URL)}
    finally:
        with admin.begin() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        admin.dispose()


def test_ready_with_plan_data(fixture_db: dict[str, str]) -> None:
    r = client(fixture_db).get("/api/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_not_ready_without_plan_data(empty_db: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        r = client(empty_db).get("/api/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready" and body["reason"] == "no_plan_data"
    assert "make ingest-dev" in body["hint"]
    assert "make ingest-dev" in caplog.text
    # Liveness stays cheap and green so the container is not restarted in a loop.
    assert client(empty_db).get("/api/health").status_code == 200


def test_not_ready_when_schema_is_missing(scratch_schema: dict[str, str]) -> None:
    """The QA symptom: a recreated tmpfs MySQL has no `msp` grants -> 1044 Access denied."""
    missing = {k: v.rsplit("/", 1)[0] + "/msp_test_missing_schema" for k, v in scratch_schema.items() if k != "name"}
    r = client(missing).get("/api/ready")
    assert r.status_code == 503
    assert r.json()["reason"] == "schema_missing"
    assert "make ingest-dev" in r.json()["hint"]


def test_not_ready_without_redis(fixture_db: dict[str, str]) -> None:
    r = client(fixture_db, redis_url="redis://:x@127.0.0.1:1/0").get("/api/ready")
    assert r.status_code == 503
    assert r.json()["reason"] == "redis_unavailable"


def test_check_data_cli(empty_db: dict[str, str], fixture_db: dict[str, str], monkeypatch: pytest.MonkeyPatch,
                        capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    from selector.cli import main
    from selector.config import get_settings

    monkeypatch.setenv("DATABASE_URL", empty_db["api"])
    get_settings.cache_clear()
    assert main(["check-data"]) == 3  # data missing: make app-up auto-loads the dev data
    assert "make ingest-dev" in capsys.readouterr().err
    monkeypatch.setenv("DATABASE_URL", fixture_db["api"])
    get_settings.cache_clear()
    assert main(["check-data"]) == 0


def test_check_data_only_skips_redis(fixture_db: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    # Host-side `make dev-data`: .env may set REDIS_URL to the container name, which the host cannot resolve.
    from selector.cli import main
    from selector.config import get_settings

    monkeypatch.setenv("DATABASE_URL", fixture_db["api"])
    monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/0")
    get_settings.cache_clear()
    assert main(["check-data"]) == 1
    assert main(["check-data", "--data-only"]) == 0
