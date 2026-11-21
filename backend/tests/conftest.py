"""Shared fixtures. Infra tests target the repo's docker-compose stack (127.0.0.1:3307 MySQL, :6380 Redis).

MySQL may instead be a shared server (`MSP_TEST_MYSQL_HOST`, `MSP_MYSQL_PORT`, `MSP_TEST_*_PASSWORD`). Redis is
app-local and never follows the MySQL host (DESIGN-v0.4-ADDENDUM A10): see `redis_test_url`.
Tests never read a `.env` file: settings are built with `_env_file=None` and explicit values.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Dev-only passwords of the compose stack (docker-compose.yml); a shared MySQL sets its own via MSP_TEST_*_PASSWORD.
DEV_PASSWORDS = {"migrator": "dev-migrator-pw", "ingest": "dev-ingest-pw", "api": "dev-api-pw", "redis": "dev-redis-pw"}


def mysql_test_url(role: str, env: Mapping[str, str] = os.environ) -> str:
    """URL of the `msp` schema for one MySQL role (`migrator`, `ingest`, `api`)."""
    host = env.get("MSP_TEST_MYSQL_HOST") or "127.0.0.1"
    port = env.get("MSP_MYSQL_PORT") or "3307"
    password = env.get(f"MSP_TEST_{role.upper()}_PASSWORD") or DEV_PASSWORDS[role]
    return f"mysql+pymysql://msp_{role}:{password}@{host}:{port}/msp"


def redis_test_url(env: Mapping[str, str] = os.environ) -> str:
    """Test Redis URL (addendum A10.4): `MSP_TEST_REDIS_URL` wins; else `MSP_TEST_REDIS_HOST` (default 127.0.0.1,
    never the MySQL host), `MSP_REDIS_PORT` (6380) and `MSP_TEST_REDIS_PASSWORD` (the compose dev password)."""
    if url := env.get("MSP_TEST_REDIS_URL"):
        return url
    host = env.get("MSP_TEST_REDIS_HOST") or "127.0.0.1"
    port = env.get("MSP_REDIS_PORT") or "6380"
    password = env.get("MSP_TEST_REDIS_PASSWORD") or DEV_PASSWORDS["redis"]
    return f"redis://:{password}@{host}:{port}/0"


MIGRATOR_URL = mysql_test_url("migrator")
INGEST_URL = mysql_test_url("ingest")
API_URL = mysql_test_url("api")
REDIS_URL = redis_test_url()


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run `docker compose` against the repo's dev/test stack."""
    return subprocess.run(  # noqa: S603
        ["docker", "compose", *args],  # noqa: S607
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make sure a stray .env in the working directory can never leak into tests."""
    from selector.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated() -> None:
    """Bring the shared `msp` schema to head and apply role grants (idempotent)."""
    from alembic.config import Config
    from sqlalchemy import create_engine

    from alembic import command
    from selector.cli import BACKEND_DIR
    from selector.grants import apply_grants

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", MIGRATOR_URL)
    command.upgrade(cfg, "head")
    eng = create_engine(MIGRATOR_URL)
    with eng.begin() as conn:
        apply_grants(conn, "msp", "msp_ingest", "msp_api")
    eng.dispose()


@pytest.fixture(scope="session")
def scratch_schema() -> Iterator[dict[str, str]]:
    """A throwaway, migrated `msp_test_*` database with role grants, so tests never touch the dev `msp` data."""
    import uuid

    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from alembic import command
    from selector.cli import BACKEND_DIR
    from selector.grants import apply_grants

    name = f"msp_test_{uuid.uuid4().hex[:8]}"
    base = MIGRATOR_URL.rsplit("/", 1)[0]
    admin = create_engine(MIGRATOR_URL)
    with admin.begin() as c:
        c.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"{base}/{name}")
    command.upgrade(cfg, "head")
    with admin.begin() as c:
        apply_grants(c, name, "msp_ingest", "msp_api")

    def url(u: str) -> str:
        return u.rsplit("/", 1)[0] + "/" + name

    try:
        yield {"name": name, "migrator": url(MIGRATOR_URL), "ingest": url(INGEST_URL), "api": url(API_URL)}
    finally:
        with admin.begin() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        admin.dispose()


@pytest.fixture(scope="session")
def fixture_db(scratch_schema: dict[str, str]) -> dict[str, str]:
    """The scratch schema with the committed CMS fixtures and dev ZIP rows loaded (what `make ingest-dev` loads)."""
    import tempfile

    from sqlalchemy import create_engine

    from selector.geo.hud import store_zip_counties
    from selector.geo.hud_file import read_hud_file
    from selector.ingest.devdata import DEV_ZIP_FILE, FIXTURE_ROOT, fixture_fetched
    from selector.ingest.run import run_ingest

    eng = create_engine(scratch_schema["ingest"])
    run_ingest(eng, 2027, sources_dir=REPO_ROOT / "sources", lock_path=Path(tempfile.mkdtemp()) / "sources.lock",
               fetched=fixture_fetched(FIXTURE_ROOT / "2027"))  # fmt: skip
    with eng.begin() as c:
        store_zip_counties(c, read_hud_file(DEV_ZIP_FILE, 2026, 2))
    eng.dispose()
    return scratch_schema
