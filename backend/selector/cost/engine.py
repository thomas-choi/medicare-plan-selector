"""Plan estimates, filters and the neutral ranking (DESIGN §6.1, §6.3).

The score uses only the user's weights over estimated total cost, worst-case cost, star rating and must-have fit.
Carrier and plan names are never inputs. Ties break by `plan_key`, so the order is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from selector.benefits.dental import NO_ROUTINE, NOT_LISTED, PlanDental, dental_drop_reason, no_dental_row
from selector.cost.medical import MedicalResult, PlanMedical, ma_medical, original_medical
from selector.cost.params import APPROXIMATION_NOTES, CostParams, Weights
from selector.cost.part_d import DrugInput, PartDResult, PlanRx, simulate_part_d

MA_CATEGORIES = ("MA", "MAPD")


@dataclass(frozen=True)
class PlanInfo:
    plan_key: str
    category: str  # MA | MAPD | PDP | SNP | other CMS categories
    plan_type: str
    org_marketing_name: str
    plan_name: str
    snp_type: str | None
    sanctioned: bool
    part_c_premium_cents: int | None
    part_d_total_premium_cents: int | None
    part_d_deductible_cents: int | None
    moop_in_network_cents: int | None
    star_overall: Decimal | None
    star_note: str | None
    part_d_suppressed: bool
    src_ref: dict[str, Any]

    @property
    def has_part_d(self) -> bool:
        return self.part_d_total_premium_cents is not None or self.category in ("MAPD", "PDP")

    @property
    def is_ma(self) -> bool:
        return self.category in MA_CATEGORIES or (self.category == "SNP")

    @property
    def monthly_premium_cents(self) -> int:
        return (self.part_c_premium_cents or 0) + (self.part_d_total_premium_cents or 0)


@dataclass(frozen=True)
class MustHaves:
    all_drugs_covered: bool = False
    plan_types: tuple[str, ...] = ()  # e.g. ("PPO",): plan_type must contain one of these
    min_stars: float | None = None
    max_moop_cents: int | None = None
    max_monthly_premium_cents: int | None = None
    dental: bool = False  # "Includes dental": at least preventive dental, without an extra premium
    dental_min_max_cents: int | None = None  # "Dental maximum at least $X" (yearly equivalent)


@dataclass(frozen=True)
class CostProfile:
    path: str = "both"  # ma | original | both
    drugs: tuple[DrugInput, ...] = ()
    utilization: str = "medium"
    must_haves: MustHaves = field(default_factory=MustHaves)
    snp_eligible: bool = False
    weights: Weights = field(default_factory=Weights)
    medigap_plan: str | None = None  # G | N | HDG: an assumption for the baseline row only (addendum A5)
    medigap_premium_monthly_cents: int | None = None  # the user's own quote; CMS publishes no Medigap premiums


@dataclass
class PlanEstimate:
    plan: PlanInfo
    path: str  # ma | original
    premium_annual_cents: int
    part_b_annual_cents: int
    drugs: PartDResult
    medical: MedicalResult
    total_low_cents: int
    total_high_cents: int
    worst_case_cents: int | None
    drugs_covered: int
    src_refs: list[dict[str, Any]]
    notes: list[str]
    dropped_reason: str | None = None
    score: float | None = None
    rank: int | None = None
    delta_vs_baseline_cents: int | None = None
    dental: PlanDental | None = None

    @property
    def total_est_cents(self) -> int:
        return (self.total_low_cents + self.total_high_cents) // 2

    @property
    def must_have_fit(self) -> float:
        n = len(self.drugs.drugs)
        return 1.0 if n == 0 else self.drugs_covered / n

    def dental_row(self) -> dict[str, Any]:
        if self.dental is not None:
            return self.dental.as_row()
        return no_dental_row(NO_ROUTINE if self.plan.category == "PDP" else NOT_LISTED)

    def as_dict(self) -> dict[str, Any]:
        p = self.plan
        return {
            "plan_key": p.plan_key,
            "plan_name": p.plan_name,
            "organization": p.org_marketing_name,
            "category": p.category,
            "plan_type": p.plan_type,
            "path": self.path,
            "snp_type": p.snp_type,
            "star_overall": float(p.star_overall) if p.star_overall is not None else None,
            "star_note": p.star_note,
            "monthly_premium_cents": p.monthly_premium_cents,
            "premium_annual_cents": self.premium_annual_cents,
            "part_b_annual_cents": self.part_b_annual_cents,
            "part_d_deductible_cents": p.part_d_deductible_cents,
            "moop_cents": p.moop_in_network_cents,
            "drug_low_cents": self.drugs.annual_low_cents,
            "drug_high_cents": self.drugs.annual_high_cents,
            "drug_monthly_low_cents": self.drugs.monthly_low_cents,
            "troop_reached_month": self.drugs.troop_reached_month,
            "medical_low_cents": self.medical.low_cents,
            "medical_high_cents": self.medical.high_cents,
            "total_low_cents": self.total_low_cents,
            "total_high_cents": self.total_high_cents,
            "total_est_cents": self.total_est_cents,
            "worst_case_cents": self.worst_case_cents,
            "drugs_covered": self.drugs_covered,
            "drugs_total": len(self.drugs.drugs),
            "drugs": [d.as_dict() for d in self.drugs.drugs],
            "dropped_reason": self.dropped_reason,
            "score": None if self.score is None else round(self.score, 4),
            "rank": self.rank,
            "delta_vs_baseline_cents": self.delta_vs_baseline_cents,
            "dental": self.dental_row(),
            "notes": self.notes,
            "src_ref": self.src_refs,
        }


def estimate_plan(
    plan: PlanInfo,
    rx: PlanRx | None,
    med: PlanMedical | None,
    profile: CostProfile,
    params: CostParams,
    dental: PlanDental | None = None,
) -> PlanEstimate:
    path = "original" if plan.category == "PDP" else "ma"
    drugs = simulate_part_d(list(profile.drugs), rx if plan.has_part_d else None, params.oop_threshold_cents)
    if path == "ma":
        medical = ma_medical(med or PlanMedical(plan.plan_key, plan.moop_in_network_cents, {}), profile.utilization)
    else:
        medical = original_medical(profile.utilization, params.medicare)
    premium = plan.monthly_premium_cents * 12
    part_b = params.part_b_premium_monthly_cents * 12
    low = premium + part_b + drugs.annual_low_cents + medical.low_cents
    high = premium + part_b + drugs.annual_high_cents + medical.high_cents
    worst: int | None = None
    if medical.worst_case_cents is not None:
        worst = premium + part_b + drugs.annual_high_cents + medical.worst_case_cents
    refs = [plan.src_ref, *drugs.src_refs, *medical.src_refs, params.part_b_src_ref]
    if params.part_d_src_ref and profile.drugs:
        refs.append(params.part_d_src_ref)
    notes = [*drugs.notes, *medical.notes]
    if plan.star_overall is None and plan.star_note:
        notes.append(f"Star rating: {plan.star_note}.")
    covered = sum(1 for d in drugs.drugs if d.covered)
    est = PlanEstimate(plan, path, premium, part_b, drugs, medical, low, high, worst, covered, refs, notes)
    est.dental = dental
    return est


def drop_reason(e: PlanEstimate, profile: CostProfile) -> str | None:
    p, mh = e.plan, profile.must_haves
    if profile.path == "ma" and e.path != "ma":
        return "Not a Medicare Advantage plan (you chose Medicare Advantage)."
    if profile.path == "original" and e.path != "original":
        return "Not a stand-alone drug plan (you chose Original Medicare + Part D)."
    if p.snp_type and not profile.snp_eligible:
        return f"Special Needs Plan ({p.snp_type}); shown only if you qualify."
    if p.sanctioned:
        return "CMS has sanctioned this plan."
    if mh.all_drugs_covered and e.drugs_covered < len(e.drugs.drugs):
        return f"Covers {e.drugs_covered} of your {len(e.drugs.drugs)} drugs."
    if mh.plan_types and not any(t.upper() in p.plan_type.upper() for t in mh.plan_types):
        return f"Plan type {p.plan_type} isn't one you asked for."
    if mh.min_stars is not None and (p.star_overall is None or float(p.star_overall) < mh.min_stars):
        return f"Star rating below {mh.min_stars}."
    if (
        mh.max_moop_cents is not None
        and e.path == "ma"
        and (p.moop_in_network_cents is None or p.moop_in_network_cents > mh.max_moop_cents)
    ):
        return "Maximum out-of-pocket is above your limit."
    if mh.max_monthly_premium_cents is not None and p.monthly_premium_cents > mh.max_monthly_premium_cents:
        return "Monthly premium is above your budget."
    if reason := dental_drop_reason(e.dental, mh.dental, mh.dental_min_max_cents):
        return reason
    if not e.drugs.estimable:
        return "CMS withheld this plan's drug data; drug costs can't be estimated (check Plan Finder)."
    return None


def _norm_lower_better(values: list[float | None]) -> list[float]:
    known = [v for v in values if v is not None]
    if not known:
        return [0.0 for _ in values]
    lo, hi = min(known), max(known)
    out = []
    for v in values:
        if v is None:
            out.append(0.0)  # no cap (or unknown) scores as the worst case
        elif hi == lo:
            out.append(1.0)
        else:
            out.append((hi - v) / (hi - lo))
    return out


def rank(estimates: list[PlanEstimate], profile: CostProfile) -> list[PlanEstimate]:
    """Set `dropped_reason`, `score` and `rank`. Returns kept plans by rank, then dropped plans by `plan_key`."""
    for e in estimates:
        e.dropped_reason = drop_reason(e, profile)
        e.score, e.rank = None, None
    kept = [e for e in estimates if e.dropped_reason is None]
    dropped = sorted((e for e in estimates if e.dropped_reason is not None), key=lambda e: e.plan.plan_key)
    w = profile.weights
    total_w = (w.total_cost + w.worst_case + w.stars + w.must_have_fit) or 1.0
    cost_n = _norm_lower_better([float(e.total_est_cents) for e in kept])
    worst_n = _norm_lower_better([None if e.worst_case_cents is None else float(e.worst_case_cents) for e in kept])
    for e, c, wc in zip(kept, cost_n, worst_n, strict=True):
        stars = float(e.plan.star_overall) / 5 if e.plan.star_overall is not None else 0.5  # unrated: neutral
        e.score = (w.total_cost * c + w.worst_case * wc + w.stars * stars + w.must_have_fit * e.must_have_fit) / total_w
    kept.sort(key=lambda e: (-(e.score or 0.0), e.plan.plan_key))
    for i, e in enumerate(kept, start=1):
        e.rank = i
    return kept + dropped


def approximation_notes(params: CostParams) -> list[str]:
    mp = params.medicare
    notes = list(APPROXIMATION_NOTES)
    notes[0] = notes[0].replace("$2,400", f"${params.oop_threshold_cents / 100:,.0f}")
    notes[3] = (
        f"Every total includes the standard Part B premium (${mp.part_b_premium_monthly_cents / 100:,.2f}/month in "
        f"{params.plan_year}). Original Medicare rows also use the ${mp.part_b_deductible_cents / 100:,.0f} Part B "
        f"deductible, {mp.part_b_coins_pct}% coinsurance and the ${mp.part_a_deductible_cents / 100:,.0f} Part A "
        "deductible for a hospital stay."
    )
    return notes


def compare(
    plans: list[PlanInfo],
    rx: dict[str, PlanRx],
    med: dict[str, PlanMedical],
    profile: CostProfile,
    params: CostParams,
    dental: dict[str, PlanDental] | None = None,
) -> list[PlanEstimate]:
    dental = dental or {}
    ests = [
        estimate_plan(p, rx.get(p.plan_key), med.get(p.plan_key), profile, params, dental.get(p.plan_key))
        for p in plans
    ]
    return rank(ests, profile)
