"""WP11 (addendum A5): the pinned "Original Medicare + Part D (standard)" baseline and the Medigap rules."""

from __future__ import annotations

import dataclasses

import pytest

from selector.cost.baseline import BASELINE_KEY, build_baseline, compare_with_baseline
from selector.cost.engine import CostProfile, MustHaves, compare
from selector.cost.medical import original_allowed_b_cents, original_medical
from selector.cost.medigap import NO_QUOTE_NOTE, apply_medigap
from selector.cost.part_d import DrugInput
from tests.unit.cost.factories import MEDICARE, PARAMS, medical, plan_info, plan_rx

FORM = {"1": 1, "2": 2, "3": 3}
GEN2 = DrugInput("generic-b", rxcui="2", user_price_cents=1_000)
BRAND = DrugInput("brand-c", rxcui="3", user_price_cents=30_000)


def _county(pdp_premiums: dict[str, int] | None = None) -> tuple[list, dict, dict]:  # type: ignore[type-arg]
    if pdp_premiums is None:
        pdp_premiums = {"S0001_001_0": 3_000, "S0002_001_0": 500}
    plans = [
        plan_info("H0001_001_0", org="Carrier A", premium_d=0, stars="4.5"),
        plan_info("H0002_001_0", org="Carrier B", premium_d=1_000, stars="3.5", plan_type="PPO"),
        *[
            plan_info(k, category="PDP", org=f"PDP {k}", premium_c=None, premium_d=v, stars="3.0")
            for k, v in pdp_premiums.items()
        ],
    ]
    rx = {p.plan_key: plan_rx(FORM, key=p.plan_key) for p in plans}
    med = {p.plan_key: medical(p.plan_key) for p in plans if p.category != "PDP"}
    return plans, rx, med


def _run(profile: CostProfile, pdp_premiums: dict[str, int] | None = None):  # type: ignore[no-untyped-def]
    plans, rx, med = _county(pdp_premiums)
    return compare_with_baseline(plans, rx, med, profile, PARAMS)


@pytest.mark.parametrize("path", ["ma", "original", "both"])
@pytest.mark.parametrize("drugs", [(), (GEN2, BRAND)])
def test_b1_baseline_on_every_path_and_with_zero_drugs(path: str, drugs: tuple[DrugInput, ...]) -> None:
    ests, b = _run(CostProfile(path=path, drugs=drugs))
    d = b.as_dict()
    assert d["plan_key"] == BASELINE_KEY and d["is_baseline"] and d["pinned"] and d["rank"] is None
    assert d["pdp_plan_key"] in {"S0001_001_0", "S0002_001_0"}
    kinds = [c["kind"] for c in d["components"]]
    assert kinds == ["part_a", "part_b", "pdp"]
    assert d["part_b_annual_cents"] == 20_940 * 12
    assert d["drugs_total"] == len(drugs)
    assert all(e.delta_vs_baseline_cents == e.total_est_cents - b.total_est_cents for e in ests)


def test_b2_pdp_is_lowest_premium_plus_drug_midpoint() -> None:
    _, b = _run(CostProfile(drugs=(GEN2, BRAND)))
    assert b.pdp is not None and b.pdp.plan.plan_key == "S0002_001_0"  # $5/month beats $30/month, same drugs
    _, b0 = _run(CostProfile())
    assert b0.pdp is not None and b0.pdp.plan.plan_key == "S0002_001_0"  # no drugs: lowest premium


def test_b2_tie_breaks_by_plan_key_not_carrier_name() -> None:
    premiums = {"S0009_001_0": 700, "S0003_001_0": 700}
    _, b = _run(CostProfile(drugs=(GEN2,)), premiums)
    assert b.pdp is not None and b.pdp.plan.plan_key == "S0003_001_0"
    plans, rx, med = _county(premiums)
    renamed = [dataclasses.replace(p, org_marketing_name="AAA first") if p.plan_key == "S0009_001_0" else p
               for p in plans]  # fmt: skip
    _, b2 = compare_with_baseline(renamed, rx, med, CostProfile(drugs=(GEN2,)), PARAMS)
    assert b2.pdp is not None and b2.pdp.plan.plan_key == "S0003_001_0"


def test_b2_suppressed_or_sanctioned_pdp_is_never_the_baseline() -> None:
    plans, rx, med = _county({"S0001_001_0": 0, "S0002_001_0": 9_000})
    plans = [dataclasses.replace(p, sanctioned=True) if p.plan_key == "S0001_001_0" else p for p in plans]
    _, b = compare_with_baseline(plans, rx, med, CostProfile(), PARAMS)
    assert b.pdp is not None and b.pdp.plan.plan_key == "S0002_001_0"


def test_b2_no_pdp_in_county_still_builds_a_baseline_with_a_note() -> None:
    plans, rx, med = _county({})
    ests, b = compare_with_baseline(plans, rx, med, CostProfile(), PARAMS)
    d = b.as_dict()
    assert b.pdp is None and d["pdp_plan_key"] is None
    assert any("No stand-alone drug plan" in n for n in d["notes"])


def test_b3_never_dropped_failed_must_haves_become_notes() -> None:
    mh = MustHaves(all_drugs_covered=True, plan_types=("PPO",), min_stars=4.5, max_moop_cents=100_000,
                   max_monthly_premium_cents=100)  # fmt: skip
    ests, b = _run(CostProfile(drugs=(GEN2, DrugInput("not-on-formulary", rxcui="999")), must_haves=mh))
    d = b.as_dict()
    assert d["dropped_reason"] is None and d["rank"] is None
    text = " ".join(d["notes"])
    for needle in ("cover all your drugs", "Medicare Advantage only", "star rating", "out-of-pocket", "budget"):
        assert needle in text, needle


def test_b4_no_medigap_medical_is_part_b_deductible_plus_20_percent() -> None:
    allowed = original_allowed_b_cents("medium")
    _, b = _run(CostProfile(utilization="medium"))
    assert b.medigap.medical.low_cents == 29_200 + round((allowed - 29_200) * 0.2)
    assert b.worst_case_cents is None and b.as_dict()["moop_cents"] is None
    _, hi = _run(CostProfile(utilization="high"))
    assert hi.medigap.medical.lines["inpatient"] == (177_600, 177_600)  # 2027 Part A deductible


def test_b5_medigap_rules() -> None:
    g = apply_medigap("G", "high", MEDICARE, 15_000)
    assert g.medical.low_cents == 29_200 and g.worst_medical_cents == 29_200
    n = apply_medigap("N", "medium", MEDICARE)
    office, er = 4 + 4 + 1, 1  # pcp + specialist + urgent care; ER visits (medium preset)
    assert n.medical.low_cents == 29_200 + office * 2_000 + er * 5_000 and n.worst_medical_cents is None
    hdg_low = apply_medigap("HDG", "low", MEDICARE)
    assert hdg_low.medical.low_cents == original_medical("low", MEDICARE).low_cents  # below the deductible
    hdg_high = apply_medigap("HDG", "high", MEDICARE)
    assert hdg_high.medical.low_cents == 305_000 == hdg_high.worst_medical_cents  # capped at $3,050
    _, b = _run(CostProfile(medigap_plan="G", medigap_premium_monthly_cents=15_000, drugs=(GEN2,)))
    assert b.worst_case_cents == (15_000 + 500) * 12 + 20_940 * 12 + b.drug_high_cents + 29_200


def test_b6_medigap_premium_only_with_a_quote() -> None:
    _, no_quote = _run(CostProfile(medigap_plan="G"))
    d = no_quote.as_dict()
    assert d["medigap"]["premium_included"] is False and NO_QUOTE_NOTE in d["notes"]
    assert d["monthly_premium_cents"] == 500  # the PDP premium only
    _, quoted = _run(CostProfile(medigap_plan="G", medigap_premium_monthly_cents=12_000))
    q = quoted.as_dict()
    assert q["medigap"]["premium_included"] is True and NO_QUOTE_NOTE not in q["notes"]
    assert q["premium_annual_cents"] == (12_000 + 500) * 12
    assert [c["kind"] for c in q["components"]] == ["part_a", "part_b", "pdp", "medigap"]
    assert q["total_low_cents"] - d["total_low_cents"] == 12_000 * 12


def test_b7_ranking_identical_with_and_without_baseline() -> None:
    plans, rx, med = _county()
    for profile in (CostProfile(drugs=(GEN2, BRAND)), CostProfile(path="ma"), CostProfile(medigap_plan="N")):
        plain = [(e.plan.plan_key, e.rank, e.score) for e in compare(plans, rx, med, profile, PARAMS)]
        ests, _ = compare_with_baseline(plans, rx, med, profile, PARAMS)
        assert [(e.plan.plan_key, e.rank, e.score) for e in ests] == plain
        assert all(e.plan.plan_key != BASELINE_KEY for e in ests)


def test_baseline_cites_part_a_part_b_and_its_pdp() -> None:
    ests, _ = _run(CostProfile(drugs=(GEN2,)))
    b = build_baseline(ests, CostProfile(drugs=(GEN2,)), PARAMS)
    rows = {r["row"] for r in b.as_dict()["src_ref"]}
    assert {"medicare_params:part_a", "medicare_params:part_b", "plan:S0002_001_0"} <= rows
