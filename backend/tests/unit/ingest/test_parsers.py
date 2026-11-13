from __future__ import annotations

from decimal import Decimal

import pytest

from selector.ingest.parsers import county_xwalk, decode, landscape, pbp, spuf
from tests.cms_fixtures import FIX


def _t(name: str) -> str:
    return decode((FIX / name).read_bytes())


def test_landscape_golden_row() -> None:
    plans = {p["plan_key"]: p for p in landscape.parse(_t("landscape.csv"), "202611")}
    g = plans["H0028_028_0"]
    assert g["category"] == "MAPD"
    assert g["part_c_premium_cents"] == 0
    assert g["part_d_deductible_cents"] == 32500
    assert g["moop_in_network_cents"] == 655000
    assert g["star_overall"] == Decimal("4.5")
    assert g["_oop_threshold_cents"] == 240000
    assert g["src_ref"] == {"source": "S1", "vintage": "202611", "row": "H0028_028_0"}
    # One row per plan even though the plan appears in several counties.
    assert len(plans) == len({p["plan_key"] for p in plans.values()})


def test_landscape_pdp_has_no_part_c_or_moop() -> None:
    pdps = [p for p in landscape.parse(_t("landscape.csv"), "v") if p["category"] == "PDP"]
    assert pdps
    for p in pdps:
        assert p["part_c_premium_cents"] is None and p["moop_in_network_cents"] is None
        assert p["pdp_region_code"] == "28"
        assert p["part_d_total_premium_cents"] is not None


def test_beneficiary_cost_codes() -> None:
    rows = [r for r in spuf.parse_beneficiary_cost(_t("cost.txt"), "v") if r["plan_key"] == "H0028_028_0"]
    by = {(r["phase"], r["tier"], r["days_supply"], r["pharmacy_type"]): r for r in rows}
    # Tier 1 initial, 30-day standard mail: $10 copay (COST_TYPE 1).
    assert by[("initial", 1, 30, "mail")]["copay_cents"] == 1000
    # Tier 3 initial, 30-day standard retail: 17% coinsurance (COST_TYPE 2), deductible applies.
    t3 = by[("initial", 3, 30, "retail")]
    assert t3["coins_pct"] == Decimal("17.00") and t3["copay_cents"] is None and t3["ded_applies"]
    # Preferred retail is "not offered" (COST_TYPE 0) for this plan → no rows.
    assert not any(r["pharmacy_type"] == "pref_retail" and r["phase"] == "initial" for r in rows)
    # Catastrophic phase present with 60-day supply code 4.
    assert ("catastrophic", 1, 60, "retail") in by
    assert by[("catastrophic", 5, 30, "retail")]["copay_cents"] == 0


def test_unknown_code_stops() -> None:
    header = "|".join(spuf.COST_HEADER)
    row = "H0028|028|000|2|1|1" + "|0|0|0|0" * 4 + "|N|N"  # COVERAGE_LEVEL 2 (old coverage gap) is not in the layout
    with pytest.raises(spuf.UnknownCode):
        list(spuf.parse_beneficiary_cost(header + "\n" + row + "\n", "v"))


def test_insulin_keeps_copay_and_coinsurance() -> None:
    rows = [r for r in spuf.parse_insulin(_t("insulin.txt"), "v") if r["plan_key"] == "H0028_028_0"]
    t3 = {(r["days_supply"], r["pharmacy_type"]): r for r in rows if r["tier"] == 3}
    assert t3[(30, "retail")]["copay_cents"] == 3500
    assert t3[(30, "retail")]["coins_pct"] == Decimal("17.00")
    assert not any(r["pharmacy_type"] == "pref_retail" for r in rows)  # blank in file


def test_pbp_minimal_services_for_golden_plan() -> None:
    rows = [r for s in ("b7", "b4", "b9") for r in pbp.parse_section(_t(f"{s}.txt"), s, "v")]
    g = {r["service_code"]: r for r in rows if r["plan_key"] == "H0028_028_0"}
    assert (g["pcp"]["copay_cents"], g["pcp"]["copay_max_cents"]) == (0, 0)
    assert g["specialist"]["copay_cents"] == 3500
    assert g["er"]["copay_cents"] == 13000
    assert g["urgent_care"]["copay_cents"] == 5000
    assert (g["outpatient"]["copay_cents"], g["outpatient"]["copay_max_cents"]) == (0, 40000)


def test_pbp_inpatient_intervals() -> None:
    out = [x for x in pbp.parse_inpatient(_t("b1a.txt"), "v") if x[1]["plan_key"] == "H0028_028_0"]
    intervals = [r for k, r in out if k == "interval"]
    assert [(i["begin_day"], i["end_day"], i["copay_per_day_cents"]) for i in intervals] == [
        (1, 6, 42500),
        (7, 90, 0),
    ]
    notes = [r for k, r in out if k == "note"]
    assert notes[0]["notes"] == "days 1-6: $425.00/day; days 7-90: $0.00/day"


def _b1a(**cols: str) -> str:
    base = {"pbp_a_hnumber": "H9999", "pbp_a_plan_identifier": "001", "segment_id": "0"}
    base.update(cols)
    return "\t".join(base) + "\n" + "\t".join(base.values()) + "\n"


def test_pbp_inpatient_flat_per_stay_and_medicare_defined() -> None:
    flat = list(pbp.parse_inpatient(_b1a(pbp_b1a_copay_mcs_amt_t1="395.00"), "v"))
    assert flat[0] == ("interval", flat[0][1])
    assert (flat[0][1]["begin_day"], flat[0][1]["end_day"], flat[0][1]["copay_per_day_cents"]) == (1, 1, 39500)
    md = list(pbp.parse_inpatient(_b1a(pbp_b1a_mc_copay_cstshr_yn_t1="1"), "v"))
    assert md == [("note", md[0][1])]
    assert md[0][1]["notes"].startswith("Original Medicare")


def test_county_crosswalk_statuses() -> None:
    xw = county_xwalk.parse_penetration(_t("penetration.csv"))
    assert xw["03060"] == "04013"  # Maricopa
    overrides = {"05201": {"ssa_code": "05201", "fips": "06037", "partial": "Y"}}
    geo = list(spuf.parse_geo(_t("geo.txt")))
    rows = {c["ssa_code"]: c for c in county_xwalk.build_counties(geo, xw, overrides, "v")}
    assert rows["03060"]["fips_status"] == "crosswalk" and rows["03060"]["fips"] == "04013"
    assert rows["05201"]["fips_status"] == "override" and rows["05201"]["partial"]
    assert rows["02013"]["fips_status"] == "pending" and rows["02013"]["fips"] is None
