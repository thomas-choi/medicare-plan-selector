"""Medigap assumptions for the Original Medicare baseline (addendum A5.3). Rules only: CMS publishes no Medigap
premiums, so a premium is added only when the user enters a quote.

| plan | what the user still pays (medical) | worst case |
|---|---|---|
| none | Part B deductible + 20% of the rest; Part A deductible per stay | no limit |
| G | the Part B deductible only | Part B deductible |
| N | Part B deductible + up to $20 per office visit + up to $50 per ER visit not admitted | no fixed limit |
| HDG | Original Medicare costs up to the high deductible (Part B deductible counts toward it) | the high deductible |

Part B excess charges are assumed $0 (doctors who accept assignment); this is labelled in the notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from selector.cost.medical import MedicalResult, original_allowed_b_cents, original_medical
from selector.cost.params import UTILIZATION, MedicareParams

MedigapPlan = Literal["G", "N", "HDG"]
LABEL: dict[str, str] = {"G": "Medigap Plan G", "N": "Medigap Plan N", "HDG": "Medigap high-deductible Plan G"}
NO_QUOTE_NOTE = "Medigap premium not included: get a quote (your State Health Insurance Assistance Program can help)."
ENROLLMENT_NOTE = (
    "Medigap: in most states you have a one-time open enrollment period; outside it, insurers may refuse you or "
    "charge more (check with SHIP)."
)


@dataclass
class MedigapResult:
    plan: str | None
    medical: MedicalResult
    worst_medical_cents: int | None  # None = no fixed yearly limit
    premium_monthly_cents: int  # 0 when no quote was entered
    premium_included: bool
    rule_note: str
    notes: list[str] = field(default_factory=list)
    src_refs: list[dict[str, Any]] = field(default_factory=list)


def apply_medigap(
    plan: str | None, utilization: str, mp: MedicareParams, quote_monthly_cents: int | None = None
) -> MedigapResult:
    om = original_medical(utilization, mp)
    if plan is None:
        return MedigapResult(
            None,
            om,
            None,
            0,
            False,
            "No Medigap: Original Medicare has no yearly out-of-pocket limit.",
            ["Original Medicare without a Medigap policy has no yearly out-of-pocket limit."],
            list(om.src_refs),
        )
    use = UTILIZATION[utilization]
    allowed_b = original_allowed_b_cents(utilization)
    part_b_ded = min(allowed_b, mp.part_b_deductible_cents)
    notes: list[str] = []
    refs = [mp.ref("part_b")]
    if plan == "G":
        med = part_b_ded
        lines = {"part_b_deductible": (med, med)}
        worst: int | None = mp.part_b_deductible_cents
        rule = (
            f"Plan G: you pay the Part B deductible (${mp.part_b_deductible_cents / 100:,.0f}); "
            "the plan pays the rest of covered costs."
        )
    elif plan == "N":
        office = use["pcp"] + use["specialist"] + use["urgent_care"]
        er = use["er"]
        copays = office * mp.medigap_n_office_copay_cents + er * mp.medigap_n_er_copay_cents
        med = part_b_ded + copays
        lines = {"part_b_deductible": (part_b_ded, part_b_ded), "plan_n_copays": (copays, copays)}
        worst = None
        rule = (
            f"Plan N: Part B deductible plus up to ${mp.medigap_n_office_copay_cents / 100:,.0f} per office visit "
            f"and up to ${mp.medigap_n_er_copay_cents / 100:,.0f} per emergency room visit that doesn't lead to "
            "admission. Part B excess charges assumed $0."
        )
        notes.append("Plan N: Part B excess charges are assumed $0 (doctors who accept Medicare assignment).")
        refs.append(mp.ref("medigap_n"))
    elif plan == "HDG":
        cap = mp.medigap_hd_deductible_cents
        med = min(om.low_cents, cap)
        lines = {"until_high_deductible": (med, med)}
        worst = cap
        rule = (
            f"High-deductible Plan G: you pay Original Medicare costs up to ${cap / 100:,.0f} a year "
            "(the Part B deductible counts toward it); then the plan pays."
        )
        refs += [mp.ref("part_a"), mp.ref("medigap_hd")]
    else:
        raise ValueError(f"unknown Medigap plan {plan!r}")
    included = quote_monthly_cents is not None
    if not included:
        notes.append(NO_QUOTE_NOTE)
    notes.append(ENROLLMENT_NOTE)
    medical = MedicalResult(med, med, med, worst, lines, refs, [])
    return MedigapResult(plan, medical, worst, quote_monthly_cents or 0, included, rule, notes, refs)
