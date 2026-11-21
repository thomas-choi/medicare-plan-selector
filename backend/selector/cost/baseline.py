"""The pinned "Original Medicare + Part D (standard)" baseline row (addendum A5).

Every comparison gets one synthetic row: Part A + Part B + the lowest-cost stand-alone drug plan (PDP) for the
user's drugs in their region, with an optional Medigap assumption. It is never ranked (`rank=None`), never dropped
by must-haves (a failed must-have adds a note instead), and is the reference for `delta_vs_baseline_cents`.

Neutrality (DESIGN §6.3): the PDP inside the baseline is chosen only by estimated cost, with the same formula for
every PDP: premium × 12 + drug-cost midpoint (no drugs: premium × 12); ties → lower worst-case drug cost →
`plan_key`. Carrier names are never inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from selector.benefits.dental import NO_ROUTINE_ORIGINAL, PlanDental, no_dental_row
from selector.cost.engine import CostProfile, PlanEstimate, PlanInfo, compare, doctor_drop_reason
from selector.cost.medical import PlanMedical
from selector.cost.medigap import LABEL, MedigapResult, apply_medigap
from selector.cost.params import CostParams
from selector.cost.part_d import PlanRx

BASELINE_KEY = "BASELINE"
BASELINE_NAME = "Original Medicare + Part D (standard)"
SWITCH_NOTE = "You can switch drug plan (PDP) in the Original Medicare rows below."
PART_A_NOTE = "Part A premium assumed $0 (most people with 40+ quarters of Medicare-covered work)."


def eligible_pdp(e: PlanEstimate) -> bool:
    p = e.plan
    return p.category == "PDP" and not p.sanctioned and not p.snp_type and e.drugs.estimable


def pdp_sort_key(e: PlanEstimate, has_drugs: bool) -> tuple[int, int, str]:
    premium = e.plan.monthly_premium_cents * 12
    if has_drugs:
        mid = (e.drugs.annual_low_cents + e.drugs.annual_high_cents) // 2
        return premium + mid, e.drugs.annual_high_cents, e.plan.plan_key
    return premium, 0, e.plan.plan_key


def choose_pdp(estimates: list[PlanEstimate], profile: CostProfile) -> PlanEstimate | None:
    cands = [e for e in estimates if eligible_pdp(e)]
    if not cands:
        return None
    return min(cands, key=lambda e: pdp_sort_key(e, bool(profile.drugs)))


@dataclass
class Baseline:
    pdp: PlanEstimate | None
    medigap: MedigapResult
    params: CostParams
    profile: CostProfile
    notes: list[str] = field(default_factory=list)
    doctors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def part_b_annual_cents(self) -> int:
        return self.params.part_b_premium_monthly_cents * 12

    @property
    def plan_premium_monthly_cents(self) -> int:
        """PDP + Medigap (when quoted). Part B is shown separately, as on every other row."""
        pdp = self.pdp.plan.monthly_premium_cents if self.pdp else 0
        return pdp + self.medigap.premium_monthly_cents

    @property
    def drug_low_cents(self) -> int:
        return self.pdp.drugs.annual_low_cents if self.pdp else 0

    @property
    def drug_high_cents(self) -> int:
        return self.pdp.drugs.annual_high_cents if self.pdp else 0

    @property
    def total_low_cents(self) -> int:
        fixed = self.plan_premium_monthly_cents * 12 + self.part_b_annual_cents
        return fixed + self.drug_low_cents + self.medigap.medical.low_cents

    @property
    def total_high_cents(self) -> int:
        fixed = self.plan_premium_monthly_cents * 12 + self.part_b_annual_cents
        return fixed + self.drug_high_cents + self.medigap.medical.high_cents

    @property
    def total_est_cents(self) -> int:
        return (self.total_low_cents + self.total_high_cents) // 2

    @property
    def worst_case_cents(self) -> int | None:
        if self.medigap.worst_medical_cents is None:
            return None
        fixed = self.plan_premium_monthly_cents * 12 + self.part_b_annual_cents
        return fixed + self.drug_high_cents + self.medigap.worst_medical_cents

    def components(self) -> list[dict[str, Any]]:
        mp = self.params.medicare
        out: list[dict[str, Any]] = [
            {"kind": "part_a", "label": "Part A (hospital)", "monthly_cents": 0, "annual_cents": 0,
             "src_ref": mp.ref("part_a")},
            {"kind": "part_b", "label": "Part B (medical)", "monthly_cents": mp.part_b_premium_monthly_cents,
             "annual_cents": mp.part_b_premium_monthly_cents * 12, "src_ref": mp.ref("part_b")},
        ]  # fmt: skip
        if self.pdp:
            p = self.pdp.plan
            out.append({"kind": "pdp", "label": p.plan_name, "plan_key": p.plan_key,
                        "organization": p.org_marketing_name, "monthly_cents": p.monthly_premium_cents,
                        "annual_cents": p.monthly_premium_cents * 12, "src_ref": p.src_ref})  # fmt: skip
        if self.medigap.plan:
            out.append({"kind": "medigap", "label": LABEL[self.medigap.plan],
                        "monthly_cents": self.medigap.premium_monthly_cents if self.medigap.premium_included else None,
                        "annual_cents": self.medigap.premium_monthly_cents * 12
                        if self.medigap.premium_included else None,
                        "src_ref": mp.ref("medigap_hd" if self.medigap.plan == "HDG" else "medigap_n"
                                          if self.medigap.plan == "N" else "part_b")})  # fmt: skip
        return out

    def as_dict(self) -> dict[str, Any]:
        mp = self.params.medicare
        pdp = self.pdp
        plan_type = "Original Medicare + PDP" + (f" + {LABEL[self.medigap.plan]}" if self.medigap.plan else "")
        drugs = pdp.drugs.drugs if pdp else []
        refs = [mp.ref("part_a"), mp.ref("part_b")]
        if pdp:
            refs += [pdp.plan.src_ref, *pdp.drugs.src_refs]
        refs += [r for r in self.medigap.src_refs if r not in refs]
        return {
            "plan_key": BASELINE_KEY,
            "plan_name": BASELINE_NAME,
            "organization": f"Original Medicare + {pdp.plan.org_marketing_name}" if pdp else "Original Medicare",
            "category": "BASELINE",
            "plan_type": plan_type,
            "path": "original",
            "snp_type": None,
            "is_baseline": True,
            "pinned": True,
            "star_overall": None,
            "star_note": None,
            "pdp_plan_key": pdp.plan.plan_key if pdp else None,
            "pdp_plan_name": pdp.plan.plan_name if pdp else None,
            "pdp_star_overall": float(pdp.plan.star_overall) if pdp and pdp.plan.star_overall is not None else None,
            "monthly_premium_cents": self.plan_premium_monthly_cents,
            "premium_annual_cents": self.plan_premium_monthly_cents * 12,
            "part_b_annual_cents": self.part_b_annual_cents,
            "part_b_deductible_cents": mp.part_b_deductible_cents,
            "part_a_deductible_cents": mp.part_a_deductible_cents,
            "part_d_deductible_cents": pdp.plan.part_d_deductible_cents if pdp else None,
            "moop_cents": self.medigap.worst_medical_cents,
            "drug_low_cents": self.drug_low_cents,
            "drug_high_cents": self.drug_high_cents,
            "drug_monthly_low_cents": pdp.drugs.monthly_low_cents if pdp else [],
            "troop_reached_month": pdp.drugs.troop_reached_month if pdp else None,
            "medical_low_cents": self.medigap.medical.low_cents,
            "medical_high_cents": self.medigap.medical.high_cents,
            "total_low_cents": self.total_low_cents,
            "total_high_cents": self.total_high_cents,
            "total_est_cents": self.total_est_cents,
            "worst_case_cents": self.worst_case_cents,
            "drugs_covered": sum(1 for d in drugs if d.covered),
            "drugs_total": len(self.profile.drugs),
            "drugs": [d.as_dict() for d in drugs],
            "dropped_reason": None,
            "score": None,
            "rank": None,
            "delta_vs_baseline_cents": 0,
            "dental": no_dental_row(NO_ROUTINE_ORIGINAL),
            "doctors": self.doctors,
            "components": self.components(),
            "medigap": {
                "plan": self.medigap.plan,
                "premium_included": self.medigap.premium_included,
                "rule_note": self.medigap.rule_note,
            },
            "notes": self.notes,
            "src_ref": refs,
        }


def must_have_notes(b: Baseline) -> list[str]:
    """The baseline is never dropped; each must-have it doesn't meet becomes a note (addendum A5.1, test B3)."""
    mh, notes = b.profile.must_haves, []
    pdp = b.pdp
    if mh.all_drugs_covered and pdp and sum(1 for d in pdp.drugs.drugs if d.covered) < len(pdp.drugs.drugs):
        notes.append("Doesn't meet your must-have: its drug plan doesn't cover all your drugs.")
    if mh.plan_types:
        notes.append("Your plan-type must-have (e.g. HMO/PPO) applies to Medicare Advantage only.")
    if mh.min_stars is not None and (
        pdp is None or pdp.plan.star_overall is None or float(pdp.plan.star_overall) < mh.min_stars
    ):
        notes.append(f"Doesn't meet your must-have: its drug plan's star rating is below {mh.min_stars}.")
    if mh.max_moop_cents is not None and (b.medigap.worst_medical_cents is None
                                          or b.medigap.worst_medical_cents > mh.max_moop_cents):  # fmt: skip
        notes.append("Doesn't meet your must-have: no yearly out-of-pocket limit at or below yours.")
    if mh.max_monthly_premium_cents is not None and b.plan_premium_monthly_cents > mh.max_monthly_premium_cents:
        notes.append("Doesn't meet your must-have: the monthly premium is above your budget.")
    if mh.dental or mh.dental_min_max_cents is not None:
        notes.append("Doesn't meet your must-have: Original Medicare doesn't cover routine dental.")
    if mh.doctors_listed and (reason := doctor_drop_reason(b.doctors)):
        notes.append(f"Doesn't meet your must-have: {reason[0].lower()}{reason[1:]}")
    return notes


def build_baseline(
    estimates: list[PlanEstimate],
    profile: CostProfile,
    params: CostParams,
    doctors: list[dict[str, Any]] | None = None,
) -> Baseline:
    """Build the baseline from the estimates `compare()` already made (PDP rows are estimated on every path).
    The Medigap assumption and quote come from the profile; `doctors` are the opt-out-list statuses."""
    pdp = choose_pdp(estimates, profile)
    mg = apply_medigap(
        profile.medigap_plan, profile.utilization, params.medicare, profile.medigap_premium_monthly_cents
    )
    b = Baseline(pdp, mg, params, profile, doctors=list(doctors or []))
    notes = [PART_A_NOTE]
    if pdp is None:
        notes.append("No stand-alone drug plan (PDP) with estimable drug costs is offered in your county.")
    else:
        notes += pdp.drugs.notes
        notes.append(SWITCH_NOTE)
    notes += mg.notes
    notes += must_have_notes(b)
    b.notes = list(dict.fromkeys(notes))
    return b


def set_deltas(estimates: list[PlanEstimate], baseline: Baseline) -> None:
    """`delta_vs_baseline_cents` on every row: estimated yearly total minus the baseline's (negative = cheaper).
    Ranks and scores are not touched (test B7)."""
    for e in estimates:
        e.delta_vs_baseline_cents = e.total_est_cents - baseline.total_est_cents


def compare_with_baseline(
    plans: list[PlanInfo],
    rx: dict[str, PlanRx],
    med: dict[str, PlanMedical],
    profile: CostProfile,
    params: CostParams,
    dental: dict[str, PlanDental] | None = None,
    doctors: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[PlanEstimate], Baseline]:
    """`compare()` (unchanged ranking) plus the pinned baseline and each row's delta to it."""
    ests = compare(plans, rx, med, profile, params, dental, doctors)
    b = build_baseline(ests, profile, params, (doctors or {}).get(BASELINE_KEY))
    set_deltas(ests, b)
    return ests, b
