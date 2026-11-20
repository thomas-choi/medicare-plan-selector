"""WP10 (addendum A5.2): the 2027 Original Medicare / Medigap amounts, cited, and no 2026 placeholder left."""

from __future__ import annotations

from pathlib import Path

import pytest

from selector.cost.engine import CostProfile, approximation_notes, estimate_plan
from selector.ingest.load import MEDICARE_GROUPS, medicare_params_row
from selector.ingest.run import load_spec
from tests.unit.cost.factories import FORM_ANY, PARAMS, medical, plan_info, plan_rx

REPO = Path(__file__).resolve().parents[4]

A5_2 = {
    "part_b_premium_cents": 20_940,
    "part_b_deductible_cents": 29_200,
    "part_b_coins_pct": 20,
    "part_a_deductible_cents": 177_600,
    "part_a_day61_cents": 44_400,
    "part_a_lifetime_cents": 88_800,
    "snf_day21_cents": 22_200,
    "medigap_hd_deductible_cents": 305_000,
    "medigap_n_office_copay_cents": 2_000,
    "medigap_n_er_copay_cents": 5_000,
}


def test_p1_2027_row_equals_addendum_values() -> None:
    row = medicare_params_row(2027, load_spec(REPO / "sources", 2027))
    assert row["plan_year"] == 2027
    assert {k: row[k] for k in A5_2} == A5_2


def test_p2_every_value_group_is_cited() -> None:
    row = medicare_params_row(2027, load_spec(REPO / "sources", 2027))
    assert set(row["src_ref"]) == set(MEDICARE_GROUPS)
    for g, ref in row["src_ref"].items():
        assert ref["url"].startswith("https://"), g
        assert ref["source"] in {"S7", "S16"} and ref["vintage"], g
    assert "2026-23601" in row["src_ref"]["part_b"]["url"]
    assert "2026-23603" in row["src_ref"]["part_a"]["url"]


def test_p2_missing_citation_is_refused() -> None:
    spec = load_spec(REPO / "sources", 2027)
    del spec["params"]["medicare"]["citations"]["part_a"]
    with pytest.raises(ValueError, match="part_a"):
        medicare_params_row(2027, spec)


def test_p3_ma_and_pdp_rows_use_2027_part_b_premium() -> None:
    ma = estimate_plan(plan_info(), plan_rx(FORM_ANY), medical(), CostProfile(), PARAMS)
    pdp = plan_info("S0001_001_0", category="PDP", premium_c=None, premium_d=500)
    od = estimate_plan(pdp, plan_rx(FORM_ANY, key="S0001_001_0"), None, CostProfile(), PARAMS)
    assert ma.part_b_annual_cents == od.part_b_annual_cents == 20_940 * 12
    assert ma.as_dict()["src_ref"][-1]["row"] == "medicare_params:part_b"


def test_p4_no_2026_placeholder_remains() -> None:
    notes = " ".join(approximation_notes(PARAMS))
    assert "placeholder" not in notes.lower() and "$209.40" in notes and "$292" in notes and "$1,776" in notes
    hits = []
    for root in (REPO / "backend" / "selector", REPO / "frontend" / "src"):
        for f in root.rglob("*"):
            if f.suffix in {".py", ".ts", ".tsx"} and "2026 placeholder" in f.read_text(encoding="utf-8"):
                hits.append(str(f.relative_to(REPO)))
    assert hits == []
