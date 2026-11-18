"""`make ingest-dev` path (fixture ingest + dev ZIP file) and ZIP→county resolution with its fallbacks."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine, text

from selector.cli import main
from selector.geo.hud import ZipCounty
from selector.geo.resolve import counties_in_state, resolve_zip
from selector.ingest.devdata import DEV_ZIP_FILE

pytestmark = pytest.mark.infra


@pytest.fixture(scope="module")
def dev_loaded(scratch_schema: dict[str, str]) -> Iterator[dict[str, str]]:
    mp = pytest.MonkeyPatch()
    mp.setenv("INGEST_DATABASE_URL", scratch_schema["ingest"])
    mp.setenv("DATABASE_URL", scratch_schema["api"])
    from selector.config import get_settings

    get_settings.cache_clear()
    assert main(["ingest", "--year", "2027", "--fixtures"]) == 0
    assert main(["hud", "load-file", str(DEV_ZIP_FILE), "--year", "2026", "--quarter", "2"]) == 0
    get_settings.cache_clear()
    mp.undo()
    yield scratch_schema


@pytest.fixture
def api_engine(dev_loaded: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(dev_loaded["api"])
    yield eng
    eng.dispose()


def test_fixture_ingest_loaded_golden_plan(api_engine: Engine) -> None:
    with api_engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2027")).scalar() == 7
        assert c.execute(text("SELECT COUNT(*) FROM zip_county_cache WHERE zip='85142'")).scalar() == 2


def test_resolve_from_cache_multi_county(api_engine: Engine) -> None:
    with api_engine.connect() as c:
        res = resolve_zip(c, "85142", hud=None, may_write_cache=False)
    assert res.source == "cache"
    assert [(o.name, o.fips) for o in res.counties] == [("Maricopa", "04013"), ("Pinal", "04021")]


def test_unknown_zip_falls_back_to_county_picker(api_engine: Engine) -> None:
    with api_engine.connect() as c:
        res = resolve_zip(c, "99999", hud=None, may_write_cache=False)
        assert res.source == "none" and res.counties == [] and res.note
        names = [o.name for o in counties_in_state(c, "AZ")]
    assert "Maricopa" in names and len(names) == 15


class _FakeHud:
    def __init__(self) -> None:
        self.calls = 0

    def zip_counties(self, z: str) -> list[ZipCounty]:
        self.calls += 1
        return [ZipCounty(z, "04019", Decimal("1"), 2026, 2)]


def test_hud_api_result_not_cached_when_not_allowed(api_engine: Engine, dev_loaded: dict[str, str]) -> None:
    hud = _FakeHud()
    with api_engine.begin() as c:
        res = resolve_zip(c, "85705", hud=hud, may_write_cache=False)  # type: ignore[arg-type]
        assert res.source == "hud_api" and res.counties[0].name == "Pima"
        assert c.execute(text("SELECT COUNT(*) FROM zip_county_cache WHERE zip='85705'")).scalar() == 0
    with api_engine.begin() as c:
        resolve_zip(c, "85705", hud=hud, may_write_cache=True)  # type: ignore[arg-type]
        assert c.execute(text("SELECT COUNT(*) FROM zip_county_cache WHERE zip='85705'")).scalar() == 1
    ing = create_engine(dev_loaded["ingest"])  # the API role can't DELETE from plan tables (read-only grant)
    with ing.begin() as c:
        c.execute(text("DELETE FROM zip_county_cache WHERE zip='85705'"))
    ing.dispose()


def test_bad_zip_rejected(api_engine: Engine) -> None:
    with api_engine.connect() as c, pytest.raises(ValueError):
        resolve_zip(c, "8500", hud=None, may_write_cache=False)
