"""Medical cost estimate (DESIGN §6.1): MA copays/coinsurance × a utilization preset, capped at the MOOP;
Original Medicare (no Medigap) as Part B deductible + 20% and the Part A deductible, with no yearly cap."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from selector.cost.params import (
    ALLOWED_CENTS,
    PART_A_DEDUCTIBLE_CENTS,
    PART_B_COINSURANCE_PCT,
    UTILIZATION,
)
from selector.cost.part_d import round_cents

SERVICES = ("pcp", "specialist", "urgent_care", "er", "outpatient")


@dataclass(frozen=True)
class Benefit:
    service_code: str
    copay_cents: int | None
    copay_max_cents: int | None
    coins_pct: Decimal | None
    coins_max_pct: Decimal | None
    src_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InpatientInterval:
    seq: int
    begin_day: int
    end_day: int
    copay_per_day_cents: int | None
    coins_pct: Decimal | None
    src_ref: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanMedical:
    plan_key: str
    moop_cents: int | None
    benefits: dict[str, Benefit]
    inpatient: list[InpatientInterval] = field(default_factory=list)


@dataclass
class MedicalResult:
    low_cents: int
    high_cents: int
    uncapped_high_cents: int
    worst_case_cents: int | None  # None = no yearly cap (Original Medicare without Medigap)
    lines: dict[str, tuple[int, int]]
    src_refs: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)


def _pct(amount: int, pct: Decimal | int) -> int:
    return round_cents(Decimal(amount) * Decimal(pct) / Decimal(100))


def _service_cost(b: Benefit | None, allowed: int) -> tuple[int, int, bool]:
    """Per-visit (low, high, known). Unknown benefit: Original-Medicare-like 20% assumption."""
    if b is None:
        v = _pct(allowed, PART_B_COINSURANCE_PCT)
        return v, v, False
    lo_opts, hi_opts = [], []
    if b.copay_cents is not None:
        lo_opts.append(b.copay_cents)
        hi_opts.append(b.copay_max_cents if b.copay_max_cents is not None else b.copay_cents)
    if b.coins_pct is not None:
        lo_opts.append(_pct(allowed, b.coins_pct))
        hi_opts.append(_pct(allowed, b.coins_max_pct if b.coins_max_pct is not None else b.coins_pct))
    if not lo_opts:
        return 0, 0, True
    return min(lo_opts), max(hi_opts), True


def ma_medical(med: PlanMedical, utilization: str) -> MedicalResult:
    use = UTILIZATION[utilization]
    lines: dict[str, tuple[int, int]] = {}
    refs: list[dict[str, Any]] = []
    notes: list[str] = []
    for svc in SERVICES:
        n = use[svc]
        b = med.benefits.get(svc)
        lo, hi, known = _service_cost(b, ALLOWED_CENTS[svc])
        if b is not None:
            refs.append(b.src_ref)
        elif n:
            notes.append(f"No {svc.replace('_', ' ')} cost sharing in the CMS file; 20% assumed.")
        lines[svc] = (lo * n, hi * n)
    days = use["inpatient_days"]
    if days:
        total = 0
        for day in range(1, days + 1):
            iv = next((i for i in med.inpatient if i.begin_day <= day <= i.end_day), None)
            if iv is None:
                total += 0 if med.inpatient else _pct(ALLOWED_CENTS["inpatient_day"], PART_B_COINSURANCE_PCT)
            elif iv.copay_per_day_cents is not None:
                total += iv.copay_per_day_cents
            elif iv.coins_pct is not None:
                total += _pct(ALLOWED_CENTS["inpatient_day"], iv.coins_pct)
        if med.inpatient:
            refs.append(med.inpatient[0].src_ref)
        else:
            notes.append("No inpatient cost sharing in the CMS file; 20% assumed.")
        lines["inpatient"] = (total, total)
    low = sum(v[0] for v in lines.values())
    high = sum(v[1] for v in lines.values())
    moop = med.moop_cents
    capped_low, capped_high = (min(low, moop), min(high, moop)) if moop is not None else (low, high)
    if moop is not None and high > moop:
        notes.append("Medical costs reach the plan's in-network maximum out-of-pocket (MOOP).")
    if moop is None:
        notes.append("No MOOP found for this plan.")
    return MedicalResult(capped_low, capped_high, high, moop, lines, refs, notes)


def original_medical(utilization: str, part_b_deductible_cents: int) -> MedicalResult:
    use = UTILIZATION[utilization]
    lines: dict[str, tuple[int, int]] = {}
    allowed_b = sum(ALLOWED_CENTS[s] * use[s] for s in SERVICES)
    if allowed_b:
        ded = min(allowed_b, part_b_deductible_cents)
        coins = _pct(allowed_b - ded, PART_B_COINSURANCE_PCT)
        lines["part_b"] = (ded + coins, ded + coins)
    if use["inpatient_days"]:
        lines["inpatient"] = (PART_A_DEDUCTIBLE_CENTS, PART_A_DEDUCTIBLE_CENTS)
    low = sum(v[0] for v in lines.values())
    return MedicalResult(
        low,
        low,
        low,
        None,
        lines,
        [{"source": "params", "vintage": "Original Medicare 2026 placeholders", "row": "part_a_b_cost_sharing"}],
        [
            "Original Medicare without a Medigap policy has no yearly out-of-pocket cap (Medigap quotes: post-MVP).",
        ],
    )
