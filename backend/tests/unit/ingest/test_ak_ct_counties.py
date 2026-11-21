"""WP19: Alaska and Connecticut SSA→FIPS mapping (DESIGN v0.5 B6, tests AK1–AK4 unit half)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from selector.geo.ct_regions import CT_PLANNING_REGIONS, legacy_fips
from selector.ingest.parsers import county_xwalk, decode, spuf
from selector.ingest.run import check_overrides_against_census
from tests.cms_fixtures import FIX, SOURCES_DIR

OVERRIDES = SOURCES_DIR / "ssa_fips_overrides.csv"


def _fixture_counties() -> dict[str, dict[str, object]]:
    geo = list(spuf.parse_geo(decode((FIX / "geo.txt").read_bytes())))
    xw = county_xwalk.parse_penetration(decode((FIX / "penetration.csv").read_bytes()))
    nber = county_xwalk.parse_nber(decode((FIX / "nber_xwalk.csv").read_bytes()))
    ov = county_xwalk.parse_overrides(OVERRIDES.read_text())
    return {c["ssa_code"]: c for c in county_xwalk.build_counties(geo, xw, ov, "v", nber)}


def test_ak1_every_ak_ct_county_gets_a_fips_or_is_retired() -> None:
    counties = _fixture_counties()
    akct = {s: c for s, c in counties.items() if c["state_name"] in ("Alaska", "Connecticut")}
    assert len(akct) == 9
    assert not [s for s, c in akct.items() if c["fips_status"] == "pending"]
    for c in akct.values():
        assert c["fips"] or c["fips_status"] == "retired", c
    assert (counties["02013"]["fips"], counties["02013"]["fips_status"]) == ("02013", "crosswalk_nber")
    # Kusilvak (formerly Wade Hampton): SSA 02270 is FIPS 02158, not 02270.
    assert counties["02270"]["fips"] == "02158"
    assert {s: counties[s]["fips"] for s in ("07000", "07010", "07040", "07060")} == {
        "07000": "09001", "07010": "09003", "07040": "09009", "07060": "09013",
    }  # fmt: skip
    assert counties["07010"]["fips_status"] == "override"


def test_ak3_chugach_and_copper_river_are_their_own_counties() -> None:
    """The 2019 Valdez-Cordova split: 02063/02066 map one-to-one; the old 02261 is retired (no FIPS)."""
    counties = _fixture_counties()
    assert (counties["02063"]["fips"], counties["02066"]["fips"]) == ("02063", "02066")
    assert (counties["02261"]["fips"], counties["02261"]["fips_status"]) == (None, "retired")


def test_xw1_and_overrides_win_over_nber() -> None:
    geo = [{"COUNTY_CODE": "03060", "STATENAME": "Arizona", "COUNTY": "Maricopa", "MA_REGION_CODE": "21",
            "PDP_REGION_CODE": "28"}]  # fmt: skip
    [c] = county_xwalk.build_counties(geo, {"03060": "04013"}, {}, "v", {"03060": "04999"})
    assert (c["fips"], c["fips_status"]) == ("04013", "crosswalk")


def test_parse_nber_needs_its_columns_and_refuses_conflicts() -> None:
    with pytest.raises(ValueError, match="ssa_code"):
        county_xwalk.parse_nber("fipscounty,state\n02013,AK\n")
    with pytest.raises(ValueError, match="two FIPS"):
        county_xwalk.parse_nber("fipscounty,ssa_code\n02013,02013\n02016,02013\n")
    got = county_xwalk.parse_nber("﻿fipscounty,ssa_code,x\n02013,02013,a\n02013,02013,b\n09110,,c\n,07000,d\n")
    assert got == {"02013": "02013"}


def test_overrides_check_accepts_cited_retired_rows(tmp_path: Path) -> None:
    assert check_overrides_against_census(OVERRIDES, FIX / "census_county.txt") == []
    bad = tmp_path / "ov.csv"
    bad.write_text("ssa_code,fips,state,county,partial,reason,citation\n02999,,AK,Nowhere,N,,\n")
    assert check_overrides_against_census(bad, FIX / "census_county.txt") == [
        "override 02999: retired SSA area (blank FIPS) needs a reason and a citation"
    ]


def test_ct_overrides_cover_all_eight_legacy_counties_one_to_one() -> None:
    ov = county_xwalk.parse_overrides(OVERRIDES.read_text())
    ct = {s: r["fips"] for s, r in ov.items() if r["state"] == "CT"}
    assert ct == {f"070{i}0": f"09{2 * i + 1:03d}" for i in range(8)}


def test_ak2_planning_regions_map_to_legacy_counties() -> None:
    assert set(CT_PLANNING_REGIONS) == {f"091{i}0" for i in range(1, 10)}
    legacy = {f"09{c:03d}" for c in range(1, 16, 2)}
    for region, (_, counties) in CT_PLANNING_REGIONS.items():
        assert {f for f, _, _ in counties} <= legacy, region
        towns = [n for _, _, n in counties]
        assert towns == sorted(towns, reverse=True), f"{region}: most towns first"
    # Every one of the 174 county-subdivision rows in the Census crosswalk is counted once.
    assert sum(n for _, (_, cs) in CT_PLANNING_REGIONS.items() for _, _, n in cs) == 174
    assert legacy_fips("09170") == ["09009"]
    assert legacy_fips("09110") == ["09003", "09013"]
    assert legacy_fips("04013") == ["04013"]


def test_ak4_no_pending_states_left() -> None:
    spec = yaml.safe_load((SOURCES_DIR / "2027.yaml").read_text())
    assert spec["pending_fips_states"] == []
    assert spec["sources"]["XW3"]["fetch"] == "file"
