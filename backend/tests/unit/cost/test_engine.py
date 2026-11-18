"""M2 cost cases: medical, totals, filters and the neutral ranking (DESIGN §6.1, §6.3)."""

from __future__ import annotations

import dataclasses
import itertools
from decimal import Decimal

import pytest

from selector.cost.engine import CostProfile, MustHaves, compare, estimate_plan, rank
from selector.cost.medical import ma_medical, original_medical
from selector.cost.params import Weights
from selector.cost.part_d import DrugInput
from tests.unit.cost.factories import PARAMS, medical, plan_info, plan_rx

FORM = {"1": 1, "2": 2, "3": 3}
GEN2 = DrugInput("generic-b", rxcui="2", user_price_cents=1_000)
PART_B_YEAR = 20_290 * 12


@pytest.mark.parametrize(
    ("utilization", "expected"),
    [
        ("low", 2 * 0 + 1 * 4_000),
        ("medium", 4 * 0 + 4 * 4_000 + 5_000 + 12_000 + 0),
        ("high", 6 * 0 + 10 * 4_000 + 2 * 5_000 + 2 * 12_000 + 3 * 0 + 5 * 40_000),
    ],
)
def test_ma_medical_low_side_by_preset(utilization: str, expected: int) -> None:
    assert ma_medical(medical(), utilization).low_cents == expected


def test_copay_range_low_and_high() -> None:
    r = ma_medical(medical(), "medium")
    assert r.high_cents - r.low_cents == 30_000  # outpatient $0-$300


def test_coinsurance_uses_allowed_amount() -> None:
    r = ma_medical(medical(specialist=(None, None, Decimal("20"), Decimal("20"))), "low")
    assert r.lines["specialist"] == (3_600, 3_600)  # 20% of $180


def test_moop_caps_medical_and_sets_worst_case() -> None:
    r = ma_medical(medical(moop=100_000), "high")
    assert r.low_cents == 100_000 and r.high_cents == 100_000 and r.uncapped_high_cents > 100_000
    assert any("MOOP" in n for n in r.notes)
    e = estimate_plan(
        plan_info(moop=100_000), plan_rx(FORM), medical(moop=100_000), CostProfile(utilization="high"), PARAMS
    )
    assert e.worst_case_cents == 0 + PART_B_YEAR + 0 + 100_000


def test_missing_benefit_assumes_20_percent_with_note() -> None:
    med = medical()
    del med.benefits["er"]
    r = ma_medical(med, "medium")
    assert r.lines["er"] == (24_000, 24_000)
    assert any("er" in n for n in r.notes)


def test_original_medicare_no_cap() -> None:
    r = original_medical("low", 28_300)
    allowed = 2 * 13_000 + 18_000
    assert r.low_cents == 28_300 + round((allowed - 28_300) * 0.2)
    assert r.worst_case_cents is None


def test_pdp_plus_part_b_placeholder() -> None:
    pdp = plan_info("S0001_001_0", category="PDP", premium_c=None, premium_d=730, stars=None)
    e = estimate_plan(
        pdp, plan_rx(FORM, key="S0001_001_0"), None, CostProfile(drugs=(GEN2,), utilization="low"), PARAMS
    )
    assert e.path == "original"
    assert e.premium_annual_cents == 730 * 12
    assert e.part_b_annual_cents == PART_B_YEAR
    assert e.total_low_cents == 730 * 12 + PART_B_YEAR + 6_000 + original_medical("low", 28_300).low_cents
    assert e.worst_case_cents is None
    assert any(r.get("source") == "S7" for r in e.src_refs)


def test_ma_only_plan_with_drugs_pays_full_price() -> None:
    ma = plan_info("H0002_001_0", category="MA", premium_d=None)
    e = estimate_plan(ma, None, medical("H0002_001_0"), CostProfile(drugs=(GEN2,)), PARAMS)
    assert e.drugs.annual_low_cents == 12_000 and e.drugs_covered == 0


def test_every_estimate_carries_src_refs() -> None:
    e = estimate_plan(plan_info(), plan_rx(FORM), medical(), CostProfile(drugs=(GEN2,)), PARAMS)
    d = e.as_dict()
    assert d["src_ref"] and all({"source", "row"} <= set(r) for r in d["src_ref"])
    assert d["plan_key"] == "H0001_001_0" and d["total_est_cents"] == e.total_est_cents


def _three() -> list:  # type: ignore[type-arg]
    return [
        plan_info("H0003_001_0", org="Carrier A", premium_d=3_000, stars="3.5"),
        plan_info("H0001_001_0", org="Carrier B", premium_d=0, stars="4.5"),
        plan_info("H0002_001_0", org="Carrier C", premium_d=1_000, stars="4.0"),
    ]


def _compare(plans: list, profile: CostProfile) -> list[str]:  # type: ignore[type-arg]
    rx = {p.plan_key: plan_rx(FORM, key=p.plan_key) for p in plans}
    med = {p.plan_key: medical(p.plan_key) for p in plans}
    return [e.plan.plan_key for e in compare(plans, rx, med, profile, PARAMS) if e.rank]


def test_ranking_by_cost() -> None:
    assert _compare(_three(), CostProfile(drugs=(GEN2,))) == ["H0001_001_0", "H0002_001_0", "H0003_001_0"]


def test_neutral_carrier_name_permutation() -> None:
    """Agent/regression test: the ranking doesn't change when carrier names are permuted."""
    base = _three()
    expected = _compare(base, CostProfile(drugs=(GEN2,)))
    for names in itertools.permutations(["Carrier A", "Carrier B", "Carrier C"]):
        renamed = [
            dataclasses.replace(p, org_marketing_name=n, plan_name=f"{n} plan")
            for p, n in zip(base, names, strict=True)
        ]
        assert _compare(renamed, CostProfile(drugs=(GEN2,))) == expected


def test_tie_breaks_by_plan_key() -> None:
    same = [plan_info(k) for k in ("H0009_001_0", "H0001_001_0", "H0005_001_0")]
    assert _compare(same, CostProfile()) == ["H0001_001_0", "H0005_001_0", "H0009_001_0"]


def test_stars_only_weights() -> None:
    order = _compare(_three(), CostProfile(weights=Weights(0, 0, 1, 0)))
    assert order == ["H0001_001_0", "H0002_001_0", "H0003_001_0"]


def test_snp_hidden_unless_eligible() -> None:
    plans = [plan_info(), plan_info("H0028_077_0", snp="Chronic or Disabling Condition")]
    assert _compare(plans, CostProfile()) == ["H0001_001_0"]
    assert set(_compare(plans, CostProfile(snp_eligible=True))) == {"H0001_001_0", "H0028_077_0"}


def test_path_filters_and_dropped_reasons() -> None:
    pdp = plan_info("S0001_001_0", category="PDP", premium_c=None, premium_d=500)
    plans = [plan_info(), pdp]
    rx = {p.plan_key: plan_rx(FORM, key=p.plan_key) for p in plans}
    med = {"H0001_001_0": medical()}
    out = compare(plans, rx, med, CostProfile(path="ma"), PARAMS)
    assert [e.plan.plan_key for e in out if e.rank] == ["H0001_001_0"]
    dropped = [e for e in out if e.dropped_reason]
    assert dropped[0].plan.plan_key == "S0001_001_0" and "Medicare Advantage" in (dropped[0].dropped_reason or "")
    assert _compare(plans, CostProfile(path="original")) == ["S0001_001_0"]


def test_must_have_all_drugs_covered() -> None:
    plans = [plan_info("H0001_001_0"), plan_info("H0002_001_0")]
    rx = {"H0001_001_0": plan_rx(FORM, key="H0001_001_0"), "H0002_001_0": plan_rx({"1": 1}, key="H0002_001_0")}
    med = {p.plan_key: medical(p.plan_key) for p in plans}
    prof = CostProfile(drugs=(GEN2,), must_haves=MustHaves(all_drugs_covered=True))
    out = compare(plans, rx, med, prof, PARAMS)
    assert [e.plan.plan_key for e in out if e.rank] == ["H0001_001_0"]
    assert "1 of your" not in (out[1].dropped_reason or "x") and "0 of your 1" in (out[1].dropped_reason or "")


def test_must_have_plan_type_stars_moop_premium() -> None:
    plans = [
        plan_info("H0001_001_0", plan_type="PPO", stars="4.5", moop=400_000, premium_d=0),
        plan_info("H0002_001_0", plan_type="HMO", stars="4.5", moop=400_000),
        plan_info("H0003_001_0", plan_type="PPO", stars="3.0"),
        plan_info("H0004_001_0", plan_type="PPO", stars="4.5", moop=900_000),
        plan_info("H0005_001_0", plan_type="PPO", stars="4.5", moop=400_000, premium_d=9_000),
    ]
    mh = MustHaves(plan_types=("PPO",), min_stars=4.0, max_moop_cents=500_000, max_monthly_premium_cents=5_000)
    assert _compare(plans, CostProfile(must_haves=mh)) == ["H0001_001_0"]


def test_uncapped_worst_case_scores_worst() -> None:
    ma = plan_info("H0001_001_0", premium_d=0)
    pdp = plan_info("S0001_001_0", category="PDP", premium_c=None, premium_d=0, stars="4.0")
    order = _compare([ma, pdp], CostProfile(weights=Weights(0, 1, 0, 0)))
    assert order[0] == "H0001_001_0"


def test_suppressed_part_d_dropped_with_reason() -> None:
    p = plan_info(suppressed=True)
    rx = {p.plan_key: plan_rx(FORM, suppressed=True)}
    out = rank(
        [estimate_plan(p, rx[p.plan_key], medical(), CostProfile(drugs=(GEN2,)), PARAMS)], CostProfile(drugs=(GEN2,))
    )
    assert out[0].rank is None and "withheld" in (out[0].dropped_reason or "")
