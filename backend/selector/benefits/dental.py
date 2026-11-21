"""Dental benefits per plan (addendum A4.4): one-line summary, must-have checks and the shapes the API, the canvas
and the agent tool return. CMS PBP b16 is the only source of these numbers.

Dental is not added to the yearly cost estimate (OPEN-QUESTIONS Q16): CMS publishes no prices for dental work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from selector.ingest.parsers.pbp_dental import PER_YEAR, PERIOD_TEXT, combined, cost_text

NO_ROUTINE = "No routine dental"
NO_ROUTINE_ORIGINAL = "No routine dental (Original Medicare and Medigap don't cover it)"
NOT_LISTED = "No dental benefit listed"
OPTIONAL_ONLY = "Optional dental package only (extra premium)"


@dataclass(frozen=True)
class PlanDental:
    plan_key: str
    has_medicare_covered: bool
    has_preventive: bool
    has_comprehensive: bool
    preventive_max_cents: int | None
    preventive_max_period: str | None
    comprehensive_max_cents: int | None
    comprehensive_max_period: str | None
    comprehensive_max_shared: bool | None
    optional_supplemental: bool
    services: list[dict[str, Any]] = field(default_factory=list)
    src_ref: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, r: Any) -> PlanDental:
        return cls(
            plan_key=r["plan_key"],
            has_medicare_covered=bool(r["has_medicare_covered"]),
            has_preventive=bool(r["has_preventive"]),
            has_comprehensive=bool(r["has_comprehensive"]),
            preventive_max_cents=r["preventive_max_cents"],
            preventive_max_period=r["preventive_max_period"],
            comprehensive_max_cents=r["comprehensive_max_cents"],
            comprehensive_max_period=r["comprehensive_max_period"],
            comprehensive_max_shared=None if r["comprehensive_max_shared"] is None
            else bool(r["comprehensive_max_shared"]),
            optional_supplemental=bool(r["optional_supplemental"]),
            services=list(r["services_json"] or []),
            src_ref=dict(r["src_ref"]),
        )  # fmt: skip

    @property
    def has_routine(self) -> bool:
        return self.has_preventive or self.has_comprehensive

    def max_cents_and_period(self) -> tuple[int | None, str | None]:
        """The largest stated maximum (preventive, or the comprehensive one when it has its own amount)."""
        cands = [(self.preventive_max_cents, self.preventive_max_period)]
        if self.comprehensive_max_shared is False:
            cands.append((self.comprehensive_max_cents, self.comprehensive_max_period))
        known = [(c, p) for c, p in cands if c is not None]
        if not known:
            return None, None
        return max(known, key=lambda cp: yearly(cp[0], cp[1]))

    def yearly_max_cents(self) -> int | None:
        """The maximum as a yearly amount ($1,500 every 3 years → $500/year). None = no maximum stated."""
        c, p = self.max_cents_and_period()
        return None if c is None else yearly(c, p)

    def summary(self) -> str:
        if not self.has_routine:
            return OPTIONAL_ONLY if self.optional_supplemental else NO_ROUTINE
        parts: list[str] = []
        prev = [s for s in self.services if s.get("group") == "preventive" and s.get("mandatory")]
        comp = [s for s in self.services if s.get("group") == "comprehensive" and s.get("mandatory")]
        if prev:
            parts.append(f"Preventive {cost_text(combined(prev))}")
        if comp:
            parts.append(f"Comprehensive {cost_text(combined(comp))}")
        parts.append(self.max_text())
        if self.optional_supplemental:
            parts.append("optional package available")
        return " · ".join(parts)

    def max_text(self) -> str:
        pv = money_period(self.preventive_max_cents, self.preventive_max_period)
        if self.comprehensive_max_shared is True:
            return f"Max {pv} (shared)" if pv else "No dental maximum stated"
        cp = money_period(self.comprehensive_max_cents, self.comprehensive_max_period)
        if pv and cp:
            return f"Max {pv} preventive, {cp} comprehensive"
        if pv:
            return f"Max {pv}"
        if cp:
            return f"Comprehensive max {cp}"
        return "No dental maximum stated"

    def as_row(self) -> dict[str, Any]:
        """What each plan row carries in the canvas (no per-service list: see `as_detail`)."""
        mx, per = self.max_cents_and_period()
        return {
            "summary": self.summary(),
            "listed": True,
            "has_preventive": self.has_preventive,
            "has_comprehensive": self.has_comprehensive,
            "max_cents": mx,
            "max_period": per,
            "max_shared": self.comprehensive_max_shared,
            "optional_supplemental": self.optional_supplemental,
            "src_ref": self.src_ref,
        }

    def as_detail(self) -> dict[str, Any]:
        """The full row for GET /api/plans/{plan_key}/benefits and the `get_plan_benefits` tool."""
        return {
            **self.as_row(),
            "has_medicare_covered": self.has_medicare_covered,
            "preventive_max_cents": self.preventive_max_cents,
            "preventive_max_period": self.preventive_max_period,
            "comprehensive_max_cents": self.comprehensive_max_cents,
            "comprehensive_max_period": self.comprehensive_max_period,
            "yearly_max_cents": self.yearly_max_cents(),
            "services": self.services,
        }


def yearly(cents: int, period: str | None) -> int:
    return int((Decimal(cents) * PER_YEAR.get(period or "year", Decimal(1))).quantize(Decimal(1), ROUND_HALF_UP))


def money_period(cents: int | None, period: str | None) -> str | None:
    if cents is None:
        return None
    text = PERIOD_TEXT.get(period or "year", "")
    sep = "" if text.startswith("/") else " "
    return f"${cents / 100:,.0f}{sep}{text}"


def no_dental_row(summary: str) -> dict[str, Any]:
    """PDPs, the baseline, and MA plans without a b16 row."""
    return {
        "summary": summary,
        "listed": summary != NOT_LISTED,
        "has_preventive": False,
        "has_comprehensive": False,
        "max_cents": None,
        "max_period": None,
        "max_shared": None,
        "optional_supplemental": False,
        "src_ref": None,
    }


def dental_drop_reason(d: PlanDental | None, want_dental: bool, min_max_cents: int | None) -> str | None:
    """Must-haves "Includes dental" and "Dental maximum at least $X" (addendum A4.4, test DN4)."""
    if not want_dental and min_max_cents is None:
        return None
    if d is None or not d.has_preventive:
        if d is not None and d.optional_supplemental:
            return "Dental only as an optional package with an extra premium (you asked for dental)."
        return "No preventive dental benefit (you asked for dental)."
    if min_max_cents is not None:
        y = d.yearly_max_cents()
        if y is not None and y < min_max_cents:
            return f"Dental maximum (about ${y / 100:,.0f} a year) is below your ${min_max_cents / 100:,.0f}."
    return None
