"""12-month Part D simulation (DESIGN §6.1).

Phases per fill, in order:
1. Catastrophic: once the member's true out-of-pocket (TrOOP) reaches the yearly threshold, covered drugs cost $0.
2. Deductible: while the plan deductible is not met, drugs in tiers where the deductible applies cost the full
   price (up to what is left of the deductible); tiers where it doesn't apply use the plan's pre-deductible row.
3. Initial coverage: the tier copay (never more than the drug's price) or coinsurance × price, clamped to the
   CMS min/max when given.
Covered insulin skips the deductible and is the lesser of copay and coinsurance, capped at $35 per month's supply.
Non-formulary drugs cost the full price and do not count toward the deductible or TrOOP.

Prices: user-entered price → plan proxy → state proxy → tier price band (a low/high range). The simulation runs
twice (low and high prices); when every price is known the two runs are identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from selector.cost.params import DEFAULT_PRICE_BAND_30D, INSULIN_MONTHLY_CAP_CENTS, TIER_PRICE_BAND_30D

FILL_MONTHS = {30: list(range(12)), 60: list(range(0, 12, 2)), 90: list(range(0, 12, 3))}


def round_cents(v: Decimal) -> int:
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class DrugInput:
    """One drug the user takes. `user_price_cents` is the full price of one fill (before insurance)."""

    name: str
    rxcui: str | None = None
    ndc: str | None = None
    days_supply: int = 30
    pharmacy: str = "retail"
    user_price_cents: int | None = None
    is_insulin: bool = False

    def __post_init__(self) -> None:
        if self.days_supply not in FILL_MONTHS:
            raise ValueError("days_supply must be 30, 60 or 90")
        if not (self.rxcui or self.ndc):
            raise ValueError(f"drug {self.name!r} needs an RxCUI or NDC")


@dataclass(frozen=True)
class FormularyEntry:
    tier: int
    prior_auth: bool = False
    step: bool = False
    qty_limit: bool = False
    src_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TierCost:
    tier: int
    phase: str  # deductible | initial | catastrophic
    pharmacy_type: str
    days_supply: int
    copay_cents: int | None
    coins_pct: Decimal | None
    coins_min_cents: int | None = None
    coins_max_cents: int | None = None
    ded_applies: bool = True
    src_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InsulinCost:
    tier: int
    pharmacy_type: str
    days_supply: int
    copay_cents: int | None
    coins_pct: Decimal | None
    src_ref: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanRx:
    """A plan's Part D data, already filtered to the user's drugs (see `repo.load_plan_rx`)."""

    plan_key: str
    deductible_cents: int
    formulary: dict[str, FormularyEntry]  # keyed by DrugInput identity (rxcui or ndc)
    tier_costs: list[TierCost]
    insulin: list[InsulinCost] = field(default_factory=list)
    suppressed: bool = False
    proxies: dict[str, int] = field(default_factory=dict)  # drug identity → 30-day price proxy (cents)
    _tc_index: dict[tuple[int, str, str, int], TierCost] = field(default_factory=dict, init=False, repr=False)
    _ins_index: dict[tuple[int, str, int], InsulinCost] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._tc_index = {(t.tier, t.phase, t.pharmacy_type, t.days_supply): t for t in self.tier_costs}
        self._ins_index = {(i.tier, i.pharmacy_type, i.days_supply): i for i in self.insulin}

    def tier_cost(self, tier: int, phase: str, pharmacy: str, days: int, *, strict: bool = False) -> TierCost | None:
        """Exact row, else the same pharmacy at 30 days, else retail / preferred retail (unless `strict`)."""
        exact = self._tc_index
        for ph in (pharmacy,) if strict else (pharmacy, "retail", "pref_retail"):
            for d in (days, 30):
                if (tier, phase, ph, d) in exact:
                    return exact[(tier, phase, ph, d)]
        return None

    def insulin_cost(self, tier: int, pharmacy: str, days: int) -> InsulinCost | None:
        exact = self._ins_index
        for t in (tier, 0):
            for ph in (pharmacy, "retail", "pref_retail"):
                for d in (days, 30):
                    if (t, ph, d) in exact:
                        return exact[(t, ph, d)]
        return None


def drug_id(d: DrugInput) -> str:
    return d.rxcui or d.ndc or ""


@dataclass
class DrugResult:
    name: str
    drug_id: str
    covered: bool
    tier: int | None
    restrictions: list[str]
    price_source: str  # user | proxy | range | full_price_unknown
    annual_low_cents: int
    annual_high_cents: int
    src_refs: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "drug_id": self.drug_id,
            "covered": self.covered,
            "tier": self.tier,
            "restrictions": self.restrictions,
            "price_source": self.price_source,
            "annual_low_cents": self.annual_low_cents,
            "annual_high_cents": self.annual_high_cents,
            "notes": self.notes,
            "src_ref": self.src_refs,
        }


@dataclass
class PartDResult:
    annual_low_cents: int
    annual_high_cents: int
    monthly_low_cents: list[int]
    monthly_high_cents: list[int]
    drugs: list[DrugResult]
    troop_reached_month: int | None  # 1-12, in the low-price run; None if never reached
    estimable: bool = True
    notes: list[str] = field(default_factory=list)
    src_refs: list[dict[str, Any]] = field(default_factory=list)


def _price_per_fill(d: DrugInput, rx: PlanRx, tier: int | None) -> tuple[int, int, str]:
    scale = Decimal(d.days_supply) / Decimal(30)
    if d.user_price_cents is not None:
        return d.user_price_cents, d.user_price_cents, "user"
    proxy = rx.proxies.get(drug_id(d))
    if proxy is not None:
        p = round_cents(Decimal(proxy) * scale)
        return p, p, "proxy"
    lo, hi = TIER_PRICE_BAND_30D.get(tier or -1, DEFAULT_PRICE_BAND_30D)
    return round_cents(Decimal(lo) * scale), round_cents(Decimal(hi) * scale), "range"


def _initial_share(tc: TierCost | None, price: int) -> int:
    if tc is None:
        return price  # cost sharing unknown: assume full price (conservative)
    if tc.copay_cents is not None:
        return min(tc.copay_cents, price)
    if tc.coins_pct is not None:
        share = round_cents(Decimal(price) * tc.coins_pct / Decimal(100))
        if tc.coins_min_cents:
            share = max(share, tc.coins_min_cents)
        if tc.coins_max_cents:
            share = min(share, tc.coins_max_cents)
        return min(share, price)
    return price


def _insulin_share(ic: InsulinCost | None, tc: TierCost | None, price: int, days: int) -> int:
    cap = INSULIN_MONTHLY_CAP_CENTS * days // 30
    options: list[int] = []
    if ic is not None:
        if ic.copay_cents is not None:
            options.append(ic.copay_cents)
        if ic.coins_pct is not None:
            options.append(round_cents(Decimal(price) * ic.coins_pct / Decimal(100)))
    if not options:
        options.append(_initial_share(tc, price))
    return min(min(options), cap, price)


@dataclass
class _Run:
    monthly: list[int]
    per_drug: dict[int, int]
    troop_month: int | None


def _simulate(drugs: list[DrugInput], rx: PlanRx, oop_threshold: int, prices: list[int]) -> _Run:
    monthly = [0] * 12
    per_drug = dict.fromkeys(range(len(drugs)), 0)
    troop = 0
    ded_left = rx.deductible_cents
    troop_month: int | None = None
    for month in range(12):
        for i, d in enumerate(drugs):
            if month not in FILL_MONTHS[d.days_supply]:
                continue
            price = prices[i]
            entry = rx.formulary.get(drug_id(d))
            if entry is None:
                pay = price  # non-formulary: full price, outside the benefit
                monthly[month] += pay
                per_drug[i] += pay
                continue
            if troop >= oop_threshold:
                pay = 0
            elif d.is_insulin:
                pay = _insulin_share(
                    rx.insulin_cost(entry.tier, d.pharmacy, d.days_supply),
                    rx.tier_cost(entry.tier, "initial", d.pharmacy, d.days_supply),
                    price,
                    d.days_supply,
                )
            else:
                initial = rx.tier_cost(entry.tier, "initial", d.pharmacy, d.days_supply)
                ded_applies = initial.ded_applies if initial is not None else True
                if ded_left > 0 and ded_applies:
                    toward = min(price, ded_left)
                    ded_left -= toward
                    rest = price - toward
                    pay = toward
                    if rest > 0:  # deductible met mid-fill: the rest at the initial cost share, pro rata
                        pay += round_cents(Decimal(_initial_share(initial, price)) * Decimal(rest) / Decimal(price))
                elif ded_left > 0:
                    pre = rx.tier_cost(entry.tier, "deductible", d.pharmacy, d.days_supply, strict=True)
                    pay = _initial_share(pre or initial, price)
                else:
                    pay = _initial_share(initial, price)
            if troop + pay > oop_threshold:
                pay = oop_threshold - troop
            troop += pay
            if troop >= oop_threshold and troop_month is None:
                troop_month = month + 1
            monthly[month] += pay
            per_drug[i] += pay
    return _Run(monthly, per_drug, troop_month)


def simulate_part_d(drugs: list[DrugInput], rx: PlanRx | None, oop_threshold_cents: int) -> PartDResult:
    if not drugs:
        return PartDResult(0, 0, [0] * 12, [0] * 12, [], None)
    if rx is None or rx.suppressed:
        reason = (
            "CMS withheld this plan's drug data, so drug costs can't be estimated; check Plan Finder."
            if rx is not None
            else "This plan has no Part D drug coverage."
        )
        mlow, mhigh = [0] * 12, [0] * 12
        uncovered: list[DrugResult] = []
        for d in drugs:
            lo, hi, src = _price_per_fill(d, rx or PlanRx("", 0, {}, []), None)
            for month in FILL_MONTHS[d.days_supply]:
                mlow[month] += lo
                mhigh[month] += hi
            n = len(FILL_MONTHS[d.days_supply])
            uncovered.append(DrugResult(d.name, drug_id(d), False, None, [], src, lo * n, hi * n, [], [reason]))
        return PartDResult(sum(mlow), sum(mhigh), mlow, mhigh, uncovered, None, estimable=rx is None, notes=[reason])

    tiers = [rx.formulary[drug_id(d)].tier if drug_id(d) in rx.formulary else None for d in drugs]
    priced = [_price_per_fill(d, rx, t) for d, t in zip(drugs, tiers, strict=True)]
    low = _simulate(drugs, rx, oop_threshold_cents, [p[0] for p in priced])
    high = _simulate(drugs, rx, oop_threshold_cents, [p[1] for p in priced])

    results: list[DrugResult] = []
    src_refs: list[dict[str, Any]] = []
    notes: list[str] = []
    for i, d in enumerate(drugs):
        entry = rx.formulary.get(drug_id(d))
        restrictions: list[str] = []
        refs: list[dict[str, Any]] = []
        dnotes: list[str] = []
        if entry is not None:
            if entry.prior_auth:
                restrictions.append("prior authorization")
            if entry.step:
                restrictions.append("step therapy")
            if entry.qty_limit:
                restrictions.append("quantity limit")
            refs.append(entry.src_ref)
            tc = rx.tier_cost(entry.tier, "initial", d.pharmacy, d.days_supply)
            if tc is not None:
                refs.append(tc.src_ref)
            else:
                dnotes.append("No cost-sharing row for this tier/pharmacy; full price assumed.")
            if d.is_insulin:
                ic = rx.insulin_cost(entry.tier, d.pharmacy, d.days_supply)
                if ic is not None:
                    refs.append(ic.src_ref)
        else:
            dnotes.append(
                "Not on this plan's formulary: full price, and it doesn't count toward the out-of-pocket cap."
            )
        src = priced[i][2]
        if src == "range":
            dnotes.append("Price unknown: shown as a range. Check Plan Finder for this drug's price.")
        results.append(
            DrugResult(
                d.name,
                drug_id(d),
                entry is not None,
                entry.tier if entry else None,
                restrictions,
                src,
                low.per_drug[i],
                high.per_drug[i],
                refs,
                dnotes,
            )
        )
        src_refs.extend(refs)
    if any(not r.covered for r in results):
        notes.append("Some drugs are not on this plan's formulary.")
    return PartDResult(
        sum(low.monthly),
        sum(high.monthly),
        low.monthly,
        high.monthly,
        results,
        low.troop_month,
        notes=notes,
        src_refs=src_refs,
    )
