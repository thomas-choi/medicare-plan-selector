"""Cost-engine assumptions (DESIGN §6.1). Every number here is an approximation shown under each estimate.

These are deliberately simple, public and identical for every plan (neutral ranking, DESIGN §6.3). Changing them
changes every plan's estimate the same way. Values in cents unless noted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Utilization = Literal["low", "medium", "high"]
Path = Literal["ma", "original", "both"]

# Yearly service counts per utilization preset (MVP: the minimal PBP services from WP1).
UTILIZATION: dict[str, dict[str, int]] = {
    "low": {"pcp": 2, "specialist": 1, "urgent_care": 0, "er": 0, "outpatient": 0, "inpatient_days": 0},
    "medium": {"pcp": 4, "specialist": 4, "urgent_care": 1, "er": 1, "outpatient": 1, "inpatient_days": 0},
    "high": {"pcp": 6, "specialist": 10, "urgent_care": 2, "er": 2, "outpatient": 3, "inpatient_days": 5},
}

# Assumed allowed amount per service (used only where a plan charges coinsurance, and for Original Medicare's 20%).
# Rough national Medicare-allowed figures, an approximation (U); labelled as such in the UI.
ALLOWED_CENTS: dict[str, int] = {
    "pcp": 13_000,
    "specialist": 18_000,
    "urgent_care": 18_000,
    "er": 120_000,
    "outpatient": 250_000,
    "inpatient_day": 300_000,
}

# Monthly (30-day) price bands per formulary tier, used when no price is known: the estimate becomes a range
# and the UI says "check Plan Finder" (DESIGN §6.1 price order, last step). Approximation (U).
TIER_PRICE_BAND_30D: dict[int, tuple[int, int]] = {
    1: (500, 2_000),  # preferred generic
    2: (1_000, 4_000),  # generic
    3: (10_000, 60_000),  # preferred brand
    4: (20_000, 80_000),  # non-preferred drug
    5: (100_000, 600_000),  # specialty
    6: (500, 3_000),  # select care / $0 tier on some plans
}
DEFAULT_PRICE_BAND_30D = (1_000, 60_000)  # tier unknown (drug not on formulary)

# Insulin: $35 per month's supply cap for covered insulin (Inflation Reduction Act).
INSULIN_MONTHLY_CAP_CENTS = 3_500

# Coinsurance assumed where a plan's cost sharing is missing from the CMS file (the Original Medicare Part B rate).
# The per-year Original Medicare amounts (Part A/B deductibles, Part B premium, Medigap rules) live in
# `medicare_params`, loaded with the ingest from cited values in sources/<year>.yaml (MedicareParams below).
PART_B_COINSURANCE_PCT = 20

PHARMACY_TYPES = ("retail", "pref_retail", "mail", "pref_mail")
DAYS_SUPPLY = (30, 60, 90)


@dataclass(frozen=True)
class Weights:
    """User weights for the neutral score (DESIGN §6.3). Only these four inputs exist; there are no sponsor fields."""

    total_cost: float = 0.6
    worst_case: float = 0.2
    stars: float = 0.1
    must_have_fit: float = 0.1

    def as_dict(self) -> dict[str, float]:
        return {
            "total_cost": self.total_cost,
            "worst_case": self.worst_case,
            "stars": self.stars,
            "must_have_fit": self.must_have_fit,
        }


@dataclass(frozen=True)
class MedicareParams:
    """Original Medicare and Medigap amounts for one plan year (addendum A5.2). Cents unless noted.

    `src_ref` maps each group (`part_b`, `part_a`, `medigap_hd`, `medigap_n`) to its citation.
    """

    part_b_premium_monthly_cents: int
    part_b_deductible_cents: int
    part_b_coins_pct: int
    part_a_deductible_cents: int
    part_a_day61_cents: int
    part_a_lifetime_cents: int
    snf_day21_cents: int
    medigap_hd_deductible_cents: int
    medigap_n_office_copay_cents: int
    medigap_n_er_copay_cents: int
    src_ref: dict[str, dict[str, Any]] = field(default_factory=dict)

    def ref(self, group: str) -> dict[str, Any]:
        return self.src_ref.get(group) or {"source": "params", "vintage": "unknown", "row": group}


@dataclass(frozen=True)
class CostParams:
    plan_year: int
    std_deductible_cents: int
    oop_threshold_cents: int
    medicare: MedicareParams
    part_d_src_ref: dict[str, Any] = field(default_factory=dict)

    @property
    def part_b_premium_monthly_cents(self) -> int:
        return self.medicare.part_b_premium_monthly_cents

    @property
    def part_b_deductible_cents(self) -> int:
        return self.medicare.part_b_deductible_cents

    @property
    def part_b_src_ref(self) -> dict[str, Any]:
        return self.medicare.ref("part_b")


APPROXIMATION_NOTES = (
    "Estimates use a 12-month Part D simulation with the plan's deductible, tier cost sharing and the "
    "$2,400 out-of-pocket threshold, after which covered drugs cost $0.",
    "Drug prices: your price if you entered one, otherwise a price range by tier until CMS publishes 2027 prices "
    "(January 2027). Check exact prices in Medicare Plan Finder.",
    "Medical costs use a simple yearly visit pattern and assumed allowed amounts; Medicare Advantage costs are "
    "capped at the plan's in-network maximum out-of-pocket (MOOP).",
    "Every total includes the standard Part B premium; Original Medicare rows also use the Part B deductible "
    "and 20% coinsurance and the Part A deductible for a hospital stay.",
    "Provider networks are not in CMS public files: call the plan to confirm your doctors.",
)
