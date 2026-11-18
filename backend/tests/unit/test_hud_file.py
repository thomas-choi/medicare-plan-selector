"""HUD fallback: quarterly ZIP_COUNTY file loader (HUD-API-SETUP.md)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from selector.geo.hud_file import HudFileError, read_hud_file, state_filter, year_quarter_from_name
from selector.ingest.devdata import DEV_ZIP_FILE


def test_dev_zip_fixture_parses() -> None:
    rows = read_hud_file(DEV_ZIP_FILE, 2026, 2)
    multi = [r for r in rows if r.zip == "85142"]
    assert {r.fips for r in multi} == {"04013", "04021"}
    assert sum(r.res_ratio for r in multi) == Decimal("1.00")
    assert all(r.hud_year == 2026 and r.hud_quarter == 2 for r in rows)


def test_year_quarter_from_hud_file_name() -> None:
    assert year_quarter_from_name(Path("ZIP_COUNTY_062026.xlsx")) == (2026, 2)
    assert year_quarter_from_name(Path("ZIP_COUNTY_122025.csv")) == (2025, 4)
    assert year_quarter_from_name(Path("zips.csv")) is None


def test_needs_year_quarter(tmp_path: Path) -> None:
    p = tmp_path / "zips.csv"
    p.write_text("ZIP,COUNTY,RES_RATIO\n85004,04013,1\n")
    with pytest.raises(HudFileError, match="year/quarter"):
        read_hud_file(p)


def test_missing_columns(tmp_path: Path) -> None:
    p = tmp_path / "ZIP_COUNTY_032026.csv"
    p.write_text("ZIPCODE,FIPS\n85004,04013\n")
    with pytest.raises(HudFileError, match="missing columns"):
        read_hud_file(p)


def test_xlsx(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["ZIP", "COUNTY", "USPS_ZIP_PREF_CITY", "USPS_ZIP_PREF_STATE", "RES_RATIO"])
    ws.append([85004, 4013, "PHOENIX", "AZ", 1])
    ws.append(["10001", "36061", "NEW YORK", "NY", 0.5])
    p = tmp_path / "ZIP_COUNTY_092026.xlsx"
    wb.save(p)
    rows = read_hud_file(p)
    assert [(r.zip, r.fips) for r in rows] == [("85004", "04013"), ("10001", "36061")]
    assert [r.fips for r in state_filter(rows, "AZ")] == ["04013"]
