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


# ---- WP19: Alaska and Connecticut (DESIGN v0.5 B6) ----


def test_ak2_ct_zip_in_a_multi_county_planning_region_offers_the_picker(api_engine: Engine) -> None:
    """Hartford 06103: HUD gives planning region 09110 (Capitol) → legacy Hartford and Tolland, with a note."""
    with api_engine.connect() as c:
        res = resolve_zip(c, "06103", hud=None, may_write_cache=False)
    assert [(o.ssa_code, o.fips, o.name) for o in res.counties] == [
        ("07010", "09003", "Hartford"),
        ("07060", "09013", "Tolland"),
    ]
    assert res.note and "planning region" in res.note


def test_ak2_ct_zip_in_a_single_county_planning_region_resolves(api_engine: Engine) -> None:
    with api_engine.connect() as c:
        res = resolve_zip(c, "06510", hud=None, may_write_cache=False)  # 09170 South Central → New Haven
    assert [(o.ssa_code, o.fips) for o in res.counties] == [("07040", "09009")] and res.note is None


def test_ak2_hud_api_planning_region_is_mapped_too(api_engine: Engine) -> None:
    class Hud:
        def zip_counties(self, z: str) -> list[ZipCounty]:
            return [ZipCounty(z, "09110", Decimal("1"), 2026, 2)]

    with api_engine.connect() as c:
        res = resolve_zip(c, "06001", hud=Hud(), may_write_cache=False)  # type: ignore[arg-type]
    assert res.source == "hud_api" and [o.ssa_code for o in res.counties] == ["07010", "07060"]


def test_ak3_chugach_and_copper_river_zips_resolve(api_engine: Engine) -> None:
    with api_engine.connect() as c:
        valdez = resolve_zip(c, "99686", hud=None, may_write_cache=False)
        copper = resolve_zip(c, "99573", hud=None, may_write_cache=False)
    assert [(o.ssa_code, o.name, o.fips_status) for o in valdez.counties] == [("02063", "Chugach", "crosswalk_nber")]
    assert [(o.ssa_code, o.name) for o in copper.counties] == [("02066", "Copper River")]


def test_ak5_county_picker_hides_retired_ssa_areas(api_engine: Engine, dev_loaded: dict[str, str]) -> None:
    # `county.state` comes from the Landscape; the fixture Landscape has no AK/CT plans (the real 2027 one has both),
    # so set the abbreviations here the way a real ingest does.
    ing = create_engine(dev_loaded["ingest"])
    with ing.begin() as c:
        c.execute(text("UPDATE county SET state='AK' WHERE state_name='Alaska'"))
        c.execute(text("UPDATE county SET state='CT' WHERE state_name='Connecticut'"))
    ing.dispose()
    with api_engine.connect() as c:
        ak = {o.ssa_code: o for o in counties_in_state(c, "AK")}
        ct = [o.fips for o in counties_in_state(c, "CT")]
    assert "02261" not in ak and {"02063", "02066", "02270"} <= set(ak)
    assert all(o.fips for o in ak.values())
    assert ct == ["09001", "09003", "09009", "09013"]


def test_ak5_zip_lookup_never_returns_a_retired_area(api_engine: Engine) -> None:
    """A stale HUD row with the pre-2019 Valdez-Cordova FIPS 02261 finds no county (that area is `retired`)."""

    class Hud:
        def zip_counties(self, z: str) -> list[ZipCounty]:
            return [ZipCounty(z, "02261", Decimal("1"), 2018, 4)]

    with api_engine.connect() as c:
        res = resolve_zip(c, "99999", hud=Hud(), may_write_cache=False)  # type: ignore[arg-type]
        assert res.counties == []
        assert c.execute(text("SELECT fips, fips_status FROM county WHERE ssa_code='02261'")).one() == (None, "retired")
