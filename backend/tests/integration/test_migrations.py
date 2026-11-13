"""Alembic upgrade/downgrade on an empty MySQL 8.4, plus role separation (DESIGN §4)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from alembic import command
from selector.cli import BACKEND_DIR
from selector.models import PLAN_TABLES, USER_TABLES, metadata
from tests.conftest import API_URL, MIGRATOR_URL

pytestmark = pytest.mark.infra


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def scratch_db() -> Iterator[str]:
    name = f"msp_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(MIGRATOR_URL)
    with admin.begin() as c:
        c.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    try:
        yield MIGRATOR_URL.rsplit("/", 1)[0] + "/" + name
    finally:
        with admin.begin() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        admin.dispose()


def test_upgrade_downgrade_upgrade(scratch_db: str) -> None:
    cfg = _cfg(scratch_db)
    command.upgrade(cfg, "head")
    eng = create_engine(scratch_db)
    tables = set(inspect(eng).get_table_names())
    assert set(metadata.tables) <= tables
    command.downgrade(cfg, "base")
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert set(metadata.tables) <= set(inspect(eng).get_table_names())
    eng.dispose()


def test_plan_tables_lead_with_plan_year(scratch_db: str) -> None:
    command.upgrade(_cfg(scratch_db), "head")
    eng = create_engine(scratch_db)
    insp = inspect(eng)
    for t in (
        "plan",
        "plan_county",
        "pbp_benefit",
        "formulary",
        "plan_formulary",
        "tier_cost",
        "insulin_cost",
    ):
        assert insp.get_pk_constraint(t)["constrained_columns"][0] == "plan_year", t
    eng.dispose()


def test_schema_has_no_sponsor_or_boost_fields() -> None:
    """Neutrality (DESIGN §6.3): nothing in the schema can carry paid placement."""
    banned = ("sponsor", "boost", "commission", "promoted", "paid")
    for t in metadata.tables.values():
        for col in t.columns:
            assert not any(b in col.name for b in banned), f"{t.name}.{col.name}"


def test_api_role_is_read_only_on_plan_tables(migrated: None) -> None:
    eng = create_engine(API_URL)
    with eng.connect() as c:
        c.execute(text("SELECT COUNT(*) FROM plan")).scalar_one()
        for t in PLAN_TABLES:
            if t == "zip_county_cache":
                continue
            with pytest.raises((OperationalError, ProgrammingError)):
                c.execute(text(f"DELETE FROM `{t}` WHERE 1=0"))
        for t in USER_TABLES:
            c.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar_one()
    eng.dispose()


def test_models_match_migrations(scratch_schema: dict[str, str]) -> None:
    """`alembic check` equivalent: a model change without a migration fails here."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    eng = create_engine(scratch_schema["migrator"])
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), metadata)
    eng.dispose()
    assert diff == []
