"""Synthetic plan data for table-driven cost tests (hand-written; not CMS rows)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from selector.cost.engine import PlanInfo
from selector.cost.medical import Benefit, InpatientInterval, PlanMedical
from selector.cost.params import CostParams, MedicareParams
from selector.cost.part_d import FormularyEntry, InsulinCost, PlanRx, TierCost

REF: dict[str, Any] = {"source": "test", "vintage": "t", "row": "r"}
# The 2027 amounts of addendum A5.2 (the same numbers sources/2027.yaml loads into medicare_params).
MEDICARE = MedicareParams(
    part_b_premium_monthly_cents=20_940,
    part_b_deductible_cents=29_200,
    part_b_coins_pct=20,
    part_a_deductible_cents=177_600,
    part_a_day61_cents=44_400,
    part_a_lifetime_cents=88_800,
    snf_day21_cents=22_200,
    medigap_hd_deductible_cents=305_000,
    medigap_n_office_copay_cents=2_000,
    medigap_n_er_copay_cents=5_000,
    src_ref={g: {"source": "S7" if g.startswith("part") else "S16", "vintage": "t", "row": f"medicare_params:{g}"}
             for g in ("part_b", "part_a", "medigap_hd", "medigap_n")},
)  # fmt: skip
PARAMS = CostParams(2027, 70_000, 240_000, MEDICARE, {"source": "S6", "row": "p"})


def tc(
    tier: int,
    phase: str,
    copay: int | None = None,
    coins: str | None = None,
    *,
    pharmacy: str = "retail",
    days: int = 30,
    ded: bool = True,
    cmin: int | None = None,
    cmax: int | None = None,
) -> TierCost:
    return TierCost(
        tier,
        phase,
        pharmacy,
        days,
        copay,
        Decimal(coins) if coins else None,
        cmin,
        cmax,
        ded,
        {**REF, "row": f"tc:{tier}:{phase}:{pharmacy}:{days}"},
    )


def standard_tiers() -> list[TierCost]:
    rows: list[TierCost] = []
    for days, mult in ((30, 1), (60, 2), (90, 3)):
        rows += [
            tc(1, "initial", 0, days=days, ded=False),
            tc(2, "initial", 500 * mult, days=days, ded=False),
            tc(3, "initial", coins="25", days=days),
            tc(4, "initial", coins="50", days=days),
            tc(5, "initial", coins="25", days=days),
            tc(1, "deductible", 0, days=days, ded=False),
            tc(2, "deductible", 500 * mult, days=days, ded=False),
        ]
    rows += [
        tc(1, "initial", 0, pharmacy="mail", days=90, ded=False),
        tc(2, "initial", 0, pharmacy="mail", days=90, ded=False),
    ]
    rows += [tc(t, "catastrophic", 0, days=d) for t in range(1, 6) for d in (30, 60, 90)]
    return rows


def plan_rx(
    formulary: dict[str, int],
    *,
    deductible: int = 59_000,
    insulin: list[InsulinCost] | None = None,
    proxies: dict[str, int] | None = None,
    suppressed: bool = False,
    key: str = "H0001_001_0",
) -> PlanRx:
    return PlanRx(
        plan_key=key,
        deductible_cents=deductible,
        formulary={d: FormularyEntry(t, src_ref={**REF, "row": f"f:{d}"}) for d, t in formulary.items()},
        tier_costs=standard_tiers(),
        insulin=insulin or [],
        suppressed=suppressed,
        proxies=proxies or {},
    )


def plan_info(
    key: str = "H0001_001_0",
    *,
    category: str = "MAPD",
    org: str = "Carrier A",
    premium_c: int | None = 0,
    premium_d: int | None = 0,
    moop: int | None = 500_000,
    stars: str | None = "4.0",
    snp: str | None = None,
    plan_type: str = "HMO",
    suppressed: bool = False,
) -> PlanInfo:
    return PlanInfo(
        plan_key=key,
        category=category,
        plan_type=plan_type,
        org_marketing_name=org,
        plan_name=f"{org} {key}",
        snp_type=snp,
        sanctioned=False,
        part_c_premium_cents=premium_c,
        part_d_total_premium_cents=premium_d,
        part_d_deductible_cents=59_000 if category in ("MAPD", "PDP") else None,
        moop_in_network_cents=moop if category != "PDP" else None,
        star_overall=Decimal(stars) if stars else None,
        star_note=None,
        part_d_suppressed=suppressed,
        src_ref={**REF, "row": f"plan:{key}"},
    )


def medical(key: str = "H0001_001_0", moop: int | None = 500_000, **benefits: tuple[Any, ...]) -> PlanMedical:
    b = {
        "pcp": Benefit("pcp", 0, 0, None, None, REF),
        "specialist": Benefit("specialist", 4_000, 4_000, None, None, REF),
        "urgent_care": Benefit("urgent_care", 5_000, 5_000, None, None, REF),
        "er": Benefit("er", 12_000, 12_000, None, None, REF),
        "outpatient": Benefit("outpatient", 0, 30_000, None, None, REF),
    }
    for k, v in benefits.items():
        b[k] = Benefit(k, *v, REF)  # type: ignore[arg-type]
    return PlanMedical(
        key, moop, b, [InpatientInterval(1, 1, 6, 40_000, None, REF), InpatientInterval(2, 7, 90, 0, None, REF)]
    )


FORM_ANY = {"1": 1, "2": 2, "3": 3}
