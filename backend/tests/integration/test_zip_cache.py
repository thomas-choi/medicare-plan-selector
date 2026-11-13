from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from selector.geo.hud import ZipCounty, cached_zip_counties, store_zip_counties

pytestmark = pytest.mark.infra


def test_cache_roundtrip_is_day_granular_and_upserts(scratch_schema: dict[str, str]) -> None:
    eng = create_engine(scratch_schema["ingest"])
    rows = [
        ZipCounty("99999", "04013", Decimal("0.75"), 2026, 3),
        ZipCounty("99999", "04021", Decimal("0.25"), 2026, 3),
    ]
    with eng.begin() as c:
        store_zip_counties(c, rows, today=dt.date(2026, 11, 13))
        store_zip_counties(c, [ZipCounty("99999", "04013", Decimal("0.80"), 2026, 4)], today=dt.date(2026, 11, 14))
    with eng.connect() as c:
        got = cached_zip_counties(c, "99999")
        assert [g.fips for g in got] == ["04013", "04021"]
        assert got[0].res_ratio == Decimal("0.80000000") and got[0].hud_quarter == 4
        col = c.execute(text("SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:s "
                             "AND TABLE_NAME='zip_county_cache' AND COLUMN_NAME='fetched_at'"),
                        {"s": scratch_schema["name"]}).scalar()  # fmt: skip
        assert col == "date"
    with eng.begin() as c:
        c.execute(text("DELETE FROM zip_county_cache WHERE zip='99999'"))
    eng.dispose()
