"""Shared fixtures. Infra tests target the repo's docker-compose stack (127.0.0.1:3307 MySQL, :6380 Redis).

Tests never read a `.env` file: settings are built with `_env_file=None` and explicit values.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MYSQL_HOST = os.environ.get("MSP_TEST_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.environ.get("MSP_MYSQL_PORT", "3307")
REDIS_PORT = os.environ.get("MSP_REDIS_PORT", "6380")

MIGRATOR_URL = f"mysql+pymysql://msp_migrator:dev-migrator-pw@{MYSQL_HOST}:{MYSQL_PORT}/msp"
INGEST_URL = f"mysql+pymysql://msp_ingest:dev-ingest-pw@{MYSQL_HOST}:{MYSQL_PORT}/msp"
API_URL = f"mysql+pymysql://msp_api:dev-api-pw@{MYSQL_HOST}:{MYSQL_PORT}/msp"
REDIS_URL = f"redis://:dev-redis-pw@{MYSQL_HOST}:{REDIS_PORT}/0"


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
