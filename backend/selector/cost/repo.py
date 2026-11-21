"""Read plan data for the cost engine (API role: read-only on plan tables)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, and_, or_, select

from selector import models as m
from selector.benefits.dental import PlanDental
from selector.config import Settings
from selector.cost.engine import PlanInfo
from selector.cost.medical import Benefit, InpatientInterval, PlanMedical
from selector.cost.params import CostParams, MedicareParams
from selector.cost.part_d import DrugInput, FormularyEntry, InsulinCost, PlanRx, TierCost, drug_id


class NoPlanData(LookupError):
    pass


def load_medicare_params(conn: Connection, year: int) -> MedicareParams:
    r = conn.execute(select(m.medicare_params).where(m.medicare_params.c.plan_year == year)).mappings().first()
    if r is None:
        raise NoPlanData(
            f"no Original Medicare parameters for {year}: re-run the ingest (make ingest-dev or make ingest)"
        )
    return MedicareParams(
        part_b_premium_monthly_cents=int(r["part_b_premium_cents"]),
        part_b_deductible_cents=int(r["part_b_deductible_cents"]),
        part_b_coins_pct=int(r["part_b_coins_pct"]),
        part_a_deductible_cents=int(r["part_a_deductible_cents"]),
        part_a_day61_cents=int(r["part_a_day61_cents"]),
        part_a_lifetime_cents=int(r["part_a_lifetime_cents"]),
        snf_day21_cents=int(r["snf_day21_cents"]),
        medigap_hd_deductible_cents=int(r["medigap_hd_deductible_cents"]),
        medigap_n_office_copay_cents=int(r["medigap_n_office_copay_cents"]),
        medigap_n_er_copay_cents=int(r["medigap_n_er_copay_cents"]),
        src_ref={k: dict(v) for k, v in dict(r["src_ref"]).items()},
    )


def load_params(conn: Connection, year: int, settings: Settings | None = None) -> CostParams:
    """Part D parameters and the Original Medicare amounts for `year` (both loaded by the ingest)."""
    row = conn.execute(select(m.part_d_params).where(m.part_d_params.c.plan_year == year)).mappings().first()
    if row is None:
        raise NoPlanData(f"no Part D parameters for {year}: run the ingest (make ingest-dev or make ingest)")
    return CostParams(
        plan_year=year,
        std_deductible_cents=row["std_deductible_cents"],
        oop_threshold_cents=row["oop_threshold_cents"],
        medicare=load_medicare_params(conn, year),
        part_d_src_ref=dict(row["src_ref"]),
    )


def _plan_info(r: Any) -> PlanInfo:
    return PlanInfo(
        plan_key=r["plan_key"],
        category=r["category"],
        plan_type=r["plan_type"],
        org_marketing_name=r["org_marketing_name"],
        plan_name=r["plan_name"],
        snp_type=r["snp_type"],
        sanctioned=bool(r["sanctioned"]),
        part_c_premium_cents=r["part_c_premium_cents"],
        part_d_total_premium_cents=r["part_d_total_premium_cents"],
        part_d_deductible_cents=r["part_d_deductible_cents"],
        moop_in_network_cents=r["moop_in_network_cents"],
        star_overall=r["star_overall"],
        star_note=r["star_note"],
        part_d_suppressed=bool(r["part_d_suppressed"]),
        src_ref=dict(r["src_ref"]),
    )


def plans_in_county(conn: Connection, year: int, ssa_code: str) -> list[PlanInfo]:
    """Every plan CMS lists for the county (none hidden for business reasons; DESIGN §8.4)."""
    p, pc = m.plan, m.plan_county
    rows = conn.execute(
        select(p)
        .join(pc, and_(pc.c.plan_year == p.c.plan_year, pc.c.plan_key == p.c.plan_key))
        .where(p.c.plan_year == year, pc.c.ssa_code == ssa_code)
        .order_by(p.c.plan_key)
    ).mappings()
    return [_plan_info(r) for r in rows]


def plans_by_key(conn: Connection, year: int, keys: Iterable[str]) -> list[PlanInfo]:
    keys = list(keys)
    if not keys:
        return []
    rows = conn.execute(
        select(m.plan).where(m.plan.c.plan_year == year, m.plan.c.plan_key.in_(keys)).order_by(m.plan.c.plan_key)
    ).mappings()
    return [_plan_info(r) for r in rows]


def plan_offered_in(conn: Connection, year: int, plan_key: str, ssa_code: str) -> bool:
    pc = m.plan_county
    return (
        conn.execute(
            select(pc.c.plan_key).where(pc.c.plan_year == year, pc.c.plan_key == plan_key, pc.c.ssa_code == ssa_code)
        ).first()
        is not None
    )


def load_plan_rx(conn: Connection, year: int, plans: list[PlanInfo], drugs: list[DrugInput]) -> dict[str, PlanRx]:
    keys = [p.plan_key for p in plans if p.has_part_d]
    if not keys:
        return {}
    pf = dict(
        conn.execute(
            select(m.plan_formulary.c.plan_key, m.plan_formulary.c.formulary_id).where(
                m.plan_formulary.c.plan_year == year, m.plan_formulary.c.plan_key.in_(keys)
            )
        ).all()
    )
    # Formulary entries for the user's drugs only: by RxCUI (lowest tier among NDCs) or exact NDC.
    fids = sorted(set(pf.values()))
    entries: dict[tuple[str, str], FormularyEntry] = {}
    rxcuis = [d.rxcui for d in drugs if d.rxcui]
    ndcs = [d.ndc for d in drugs if d.ndc and not d.rxcui]
    if fids and (rxcuis or ndcs):
        f = m.formulary
        conds = []
        if rxcuis:
            conds.append(f.c.rxcui.in_(rxcuis))
        if ndcs:
            conds.append(f.c.ndc.in_(ndcs))
        rows = conn.execute(
            select(f).where(f.c.plan_year == year, f.c.formulary_id.in_(fids), or_(*conds)).order_by(f.c.ndc)
        ).mappings()
        for r in rows:
            for d in drugs:
                if (d.rxcui and r["rxcui"] == d.rxcui) or (not d.rxcui and d.ndc and r["ndc"] == d.ndc):
                    ek = (r["formulary_id"], drug_id(d))
                    cur = entries.get(ek)
                    if cur is None or r["tier"] < cur.tier:
                        entries[ek] = FormularyEntry(
                            int(r["tier"]),
                            bool(r["prior_auth"]),
                            bool(r["step"]),
                            bool(r["qty_limit"]),
                            dict(r["src_ref"]),
                        )
    tcs: dict[str, list[TierCost]] = {k: [] for k in keys}
    for r in conn.execute(
        select(m.tier_cost).where(m.tier_cost.c.plan_year == year, m.tier_cost.c.plan_key.in_(keys))
    ).mappings():
        tcs[r["plan_key"]].append(
            TierCost(
                int(r["tier"]),
                r["phase"],
                r["pharmacy_type"],
                int(r["days_supply"]),
                r["copay_cents"],
                r["coins_pct"],
                r["coins_min_cents"],
                r["coins_max_cents"],
                bool(r["ded_applies"]),
                dict(r["src_ref"]),
            )
        )
    ins: dict[str, list[InsulinCost]] = {k: [] for k in keys}
    if any(d.is_insulin for d in drugs):
        for r in conn.execute(
            select(m.insulin_cost).where(m.insulin_cost.c.plan_year == year, m.insulin_cost.c.plan_key.in_(keys))
        ).mappings():
            ins[r["plan_key"]].append(
                InsulinCost(
                    int(r["tier"]),
                    r["pharmacy_type"],
                    int(r["days_supply"]),
                    r["copay_cents"],
                    r["coins_pct"],
                    dict(r["src_ref"]),
                )
            )
    out: dict[str, PlanRx] = {}
    by_key = {p.plan_key: p for p in plans}
    for k in keys:
        p = by_key[k]
        fid = pf.get(k)
        formulary = {did: e for (f_id, did), e in entries.items() if f_id == fid}
        out[k] = PlanRx(
            plan_key=k,
            deductible_cents=p.part_d_deductible_cents or 0,
            formulary=formulary,
            tier_costs=tcs[k],
            insulin=ins[k],
            suppressed=p.part_d_suppressed or fid is None,
        )
    return out


def load_plan_medical(conn: Connection, year: int, plans: list[PlanInfo]) -> dict[str, PlanMedical]:
    keys = [p.plan_key for p in plans if p.category != "PDP"]
    if not keys:
        return {}
    out = {
        p.plan_key: PlanMedical(p.plan_key, p.moop_in_network_cents, {}, []) for p in plans if p.plan_key in set(keys)
    }
    for r in conn.execute(
        select(m.pbp_benefit).where(m.pbp_benefit.c.plan_year == year, m.pbp_benefit.c.plan_key.in_(keys))
    ).mappings():
        if r["service_code"] == "inpatient":
            continue  # per-day intervals come from pbp_inpatient_interval
        out[r["plan_key"]].benefits[r["service_code"]] = Benefit(
            r["service_code"],
            r["copay_cents"],
            r["copay_max_cents"],
            r["coins_pct"],
            r["coins_max_pct"],
            dict(r["src_ref"]),
        )
    for r in conn.execute(
        select(m.pbp_inpatient_interval)
        .where(m.pbp_inpatient_interval.c.plan_year == year, m.pbp_inpatient_interval.c.plan_key.in_(keys))
        .order_by(m.pbp_inpatient_interval.c.plan_key, m.pbp_inpatient_interval.c.seq)
    ).mappings():
        out[r["plan_key"]].inpatient.append(
            InpatientInterval(
                int(r["seq"]),
                int(r["begin_day"]),
                int(r["end_day"]),
                r["copay_per_day_cents"],
                r["coins_pct"],
                dict(r["src_ref"]),
            )
        )
    return out


def drug_on_any_formulary(conn: Connection, year: int, rxcui: str) -> bool:
    f = m.formulary
    return conn.execute(select(f.c.ndc).where(f.c.plan_year == year, f.c.rxcui == rxcui).limit(1)).first() is not None


def load_plan_dental(conn: Connection, year: int, plans: list[PlanInfo]) -> dict[str, PlanDental]:
    keys = [p.plan_key for p in plans if p.category != "PDP"]
    if not keys:
        return {}
    d = m.plan_dental
    rows = conn.execute(select(d).where(d.c.plan_year == year, d.c.plan_key.in_(keys))).mappings()
    return {r["plan_key"]: PlanDental.from_row(r) for r in rows}


def plan_dental_one(conn: Connection, year: int, plan_key: str) -> PlanDental | None:
    d = m.plan_dental
    r = conn.execute(select(d).where(d.c.plan_year == year, d.c.plan_key == plan_key)).mappings().first()
    return PlanDental.from_row(r) if r is not None else None
