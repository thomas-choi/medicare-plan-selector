"""M2 cost cases (IMPLEMENTATION-PLAN regression suite): Part D simulation, table-driven."""

from __future__ import annotations

from decimal import Decimal

import pytest

from selector.cost.part_d import DrugInput, InsulinCost, simulate_part_d
from tests.unit.cost.factories import REF, plan_rx

OOP = 240_000
GEN = DrugInput("generic-a", rxcui="1", user_price_cents=1_000)
GEN2 = DrugInput("generic-b", rxcui="2", user_price_cents=1_000)
BRAND = DrugInput("brand-c", rxcui="3", user_price_cents=30_000)
SPEC = DrugInput("specialty-d", rxcui="5", user_price_cents=500_000)
FORM = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "9": 3}


@pytest.mark.parametrize(
    ("case", "drugs", "expected_low", "expected_high"),
    [
        ("zero drugs", [], 0, 0),
        ("tier 1 generic $0 copay", [GEN], 0, 0),
        ("tier 2 generic $5 copay, 30-day", [GEN2], 6_000, 6_000),
        (
            "tier 2, 90-day retail ($15 × 4 fills)",
            [DrugInput("g", rxcui="2", days_supply=90, user_price_cents=3_000)],
            6_000,
            6_000,
        ),
        (
            "tier 2, 60-day retail ($10 × 6 fills)",
            [DrugInput("g", rxcui="2", days_supply=60, user_price_cents=2_000)],
            6_000,
            6_000,
        ),
        (
            "tier 2, 90-day mail order $0",
            [DrugInput("g", rxcui="2", days_supply=90, pharmacy="mail", user_price_cents=3_000)],
            0,
            0,
        ),
        ("copay never above the price", [DrugInput("g", rxcui="2", user_price_cents=300)], 3_600, 3_600),
        ("deductible crossover in month 2", [BRAND], 134_250, 134_250),
        ("TrOOP cap reached mid-year", [SPEC], OOP, OOP),
        ("non-formulary drug: full price", [DrugInput("x", rxcui="404", user_price_cents=10_000)], 120_000, 120_000),
        (
            "non-formulary doesn't count toward TrOOP",
            [SPEC, DrugInput("x", rxcui="404", user_price_cents=10_000)],
            OOP + 120_000,
            OOP + 120_000,
        ),
        ("missing price becomes a tier range", [DrugInput("brand", rxcui="9")], 12 * 2_500 + 0, None),
    ],
)
def test_part_d_cases(case: str, drugs: list[DrugInput], expected_low: int, expected_high: int | None) -> None:
    res = simulate_part_d(drugs, plan_rx(FORM), OOP)
    if case.startswith("missing price"):
        # Tier 3 band $100-$600/month, 25% after a $590 deductible.
        assert res.annual_low_cents < res.annual_high_cents
        assert res.drugs[0].price_source == "range"
        assert any("range" in n for n in res.drugs[0].notes)
        return
    assert res.annual_low_cents == expected_low, case
    assert res.annual_high_cents == (expected_high if expected_high is not None else expected_low), case


def test_deductible_crossover_by_month() -> None:
    res = simulate_part_d([BRAND], plan_rx(FORM), OOP)
    # $300 toward the $590 deductible, then $290 + 25% of the $10 left ($2.50), then 25% of $300.
    assert res.monthly_low_cents[:3] == [30_000, 29_250, 7_500]


def test_troop_month_and_zero_after() -> None:
    res = simulate_part_d([SPEC], plan_rx(FORM), OOP)
    assert res.troop_reached_month == 2
    assert res.monthly_low_cents[2:] == [0] * 10
    assert sum(res.monthly_low_cents) == OOP


def test_tier_without_deductible_uses_pre_deductible_row() -> None:
    res = simulate_part_d([GEN2, BRAND], plan_rx(FORM), OOP)
    assert res.monthly_low_cents[0] == 500 + 30_000


def test_insulin_skips_deductible_and_is_capped() -> None:
    ins = [InsulinCost(3, "retail", 30, 4_700, None, REF), InsulinCost(3, "retail", 90, 14_100, None, REF)]
    rx = plan_rx({"ins": 3}, insulin=ins)
    monthly = simulate_part_d([DrugInput("insulin", rxcui="ins", user_price_cents=40_000, is_insulin=True)], rx, OOP)
    assert monthly.annual_low_cents == 12 * 3_500  # $47 copay capped at $35/month
    q = simulate_part_d(
        [DrugInput("insulin", rxcui="ins", days_supply=90, user_price_cents=120_000, is_insulin=True)], rx, OOP
    )
    assert q.annual_low_cents == 4 * 10_500


def test_insulin_lesser_of_copay_and_coinsurance() -> None:
    ins = [InsulinCost(3, "retail", 30, 3_000, Decimal("10"), REF)]
    rx = plan_rx({"ins": 3}, insulin=ins)
    res = simulate_part_d([DrugInput("insulin", rxcui="ins", user_price_cents=20_000, is_insulin=True)], rx, OOP)
    assert res.annual_low_cents == 12 * 2_000  # 10% of $200 < $30 copay


def test_price_order_user_then_proxy_then_range() -> None:
    rx = plan_rx(FORM, proxies={"3": 20_000})
    proxied = simulate_part_d([DrugInput("b", rxcui="3")], rx, OOP).drugs[0]
    assert proxied.price_source == "proxy" and proxied.annual_low_cents == proxied.annual_high_cents
    user = simulate_part_d([DrugInput("b", rxcui="3", user_price_cents=5_000)], rx, OOP).drugs[0]
    assert user.price_source == "user"
    ranged = simulate_part_d([DrugInput("b", rxcui="9")], rx, OOP).drugs[0]
    assert ranged.price_source == "range"


def test_rounding_half_up_per_fill() -> None:
    rx = plan_rx({"c": 3}, deductible=0)
    res = simulate_part_d([DrugInput("c", rxcui="c", user_price_cents=12_345)], rx, OOP)
    assert res.monthly_low_cents[0] == 3_086  # 25% of $123.45 = $30.8625 → $30.86
    assert sum(res.monthly_low_cents) == 12 * 3_086
    # The pro-rata split in the deductible month rounds half-up too: 2 cents left × 25% = 0.5 cent → 1 cent.
    odd = simulate_part_d(
        [DrugInput("c", rxcui="c", user_price_cents=30_000)], plan_rx({"c": 3}, deductible=29_998), OOP
    )
    assert odd.monthly_low_cents[0] == 29_998 + 1


def test_no_part_d_plan_pays_full_price() -> None:
    res = simulate_part_d([GEN2], None, OOP)
    assert res.annual_low_cents == 12_000 and res.estimable
    assert not res.drugs[0].covered


def test_suppressed_plan_not_estimable() -> None:
    res = simulate_part_d([GEN2], plan_rx(FORM, suppressed=True), OOP)
    assert not res.estimable and "withheld" in res.notes[0]


def test_restrictions_and_src_refs() -> None:
    rx = plan_rx(FORM)
    rx.formulary["3"] = type(rx.formulary["3"])(3, prior_auth=True, step=True, qty_limit=True, src_ref=REF)
    d = simulate_part_d([BRAND], rx, OOP).drugs[0]
    assert d.restrictions == ["prior authorization", "step therapy", "quantity limit"]
    assert d.src_refs and all("source" in r for r in d.src_refs)


def test_days_supply_validated() -> None:
    with pytest.raises(ValueError):
        DrugInput("x", rxcui="1", days_supply=45)
    with pytest.raises(ValueError):
        DrugInput("x")
