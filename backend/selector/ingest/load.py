"""Build all plan-data rows for one `plan_year` and swap them in (DESIGN §4).

The swap is delete-and-insert inside one transaction for that year, so other years are untouched and a failed
validation rolls everything back. `county` holds geography for all years and is replaced as a whole.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Table, delete, insert

from selector import models as m
from selector.ingest.fetch import Fetched
from selector.ingest.manifest import sha256_bytes
from selector.ingest.normalize import src_ref
from selector.ingest.parsers import county_xwalk, decode, landscape, pbp, read_delimited, spuf

BATCH = 5000
YEAR_TABLES: Sequence[Table] = (
    m.plan,
    m.plan_county,
    m.pbp_benefit,
    m.pbp_inpatient_interval,
    m.formulary,
    m.plan_formulary,
    m.tier_cost,
    m.insulin_cost,
    m.part_d_params,
)


@dataclass
class YearData:
    year: int
    plans: list[dict[str, Any]] = field(default_factory=list)
    counties: list[dict[str, Any]] = field(default_factory=list)
    plan_county: list[dict[str, Any]] = field(default_factory=list)
    pbp_benefit: list[dict[str, Any]] = field(default_factory=list)
    inpatient: list[dict[str, Any]] = field(default_factory=list)
    formulary: list[dict[str, Any]] = field(default_factory=list)
    plan_formulary: list[dict[str, Any]] = field(default_factory=list)
    tier_cost: list[dict[str, Any]] = field(default_factory=list)
    insulin: list[dict[str, Any]] = field(default_factory=list)
    part_d_params: dict[str, Any] = field(default_factory=dict)
    oop_thresholds: set[int] = field(default_factory=set)

    def rows_for(self, table: Table) -> list[dict[str, Any]]:
        return {
            "plan": self.plans,
            "plan_county": self.plan_county,
            "pbp_benefit": self.pbp_benefit,
            "pbp_inpatient_interval": self.inpatient,
            "formulary": self.formulary,
            "plan_formulary": self.plan_formulary,
            "tier_cost": self.tier_cost,
            "insulin_cost": self.insulin,
            "part_d_params": [self.part_d_params] if self.part_d_params else [],
        }[table.name]


def _read(p: Path) -> str:
    return decode(p.read_bytes())


def build_year(year: int, fetched: dict[str, Fetched], spec: dict[str, Any], overrides_csv: Path) -> YearData:
    d = YearData(year)
    s1, s2, s3, xw1 = fetched["S1"], fetched["S2"], fetched["S3"], fetched["XW1"]

    # Plans (S1). Landscape is the authoritative plan list; other files are filtered to it.
    landscape_text = _read(s1.paths["landscape"])
    state_abbr: dict[str, str] = {}
    for r in read_delimited(landscape_text, ",", landscape.EXPECTED_HEADER):
        state_abbr.setdefault(r["State Territory Name"].strip(), r["State Territory Abbreviation"].strip())
    for p in landscape.parse(landscape_text, s1.entry.vintage):
        oop = p.pop("_oop_threshold_cents")
        if oop is not None:
            d.oop_thresholds.add(oop)
        d.plans.append({"plan_year": year, **p})
    plan_keys = {p["plan_key"] for p in d.plans}

    # Counties (S3 geo locator + SSA→FIPS crosswalk + cited overrides).
    xwalk = county_xwalk.parse_penetration(_read(xw1.paths["penetration"]))
    overrides = county_xwalk.parse_overrides(overrides_csv.read_text())
    geo = list(spuf.parse_geo(_read(s3.paths["geo"])))
    counties = list(county_xwalk.build_counties(geo, xwalk, overrides, s3.entry.vintage))
    per_fips: dict[str, int] = defaultdict(int)
    for c in counties:
        c["state"] = state_abbr.get(c["state_name"])
        if c["fips"]:
            per_fips[c["fips"]] += 1
    for c in counties:
        if c["fips"] and per_fips[c["fips"]] > 1:
            c["partial"] = True  # several SSA rating codes share this county
    d.counties = counties

    # Service area: MA from PBP PlanArea; PDP from its PDP region.
    pc: set[tuple[str, str]] = set()
    for r in pbp.parse_plan_area(_read(s2.paths["plan_area"])):
        if r["plan_key"] in plan_keys:
            pc.add((r["plan_key"], r["ssa_code"]))
    by_region: dict[str, list[str]] = defaultdict(list)
    for c in counties:
        if c["pdp_region_code"]:
            by_region[c["pdp_region_code"]].append(c["ssa_code"])
    by_ma_region: dict[str, list[str]] = defaultdict(list)
    for c in counties:
        if c["ma_region_code"]:
            by_ma_region[c["ma_region_code"]].append(c["ssa_code"])
    in_plan_area = {k for k, _ in pc}
    for p in d.plans:
        if p["category"] == "PDP" and p["pdp_region_code"]:
            for ssa in by_region.get(p["pdp_region_code"], []):
                pc.add((p["plan_key"], ssa))
        elif p["plan_key"] not in in_plan_area and p["plan_type"].startswith("Regional PPO") and p["ma_region_code"]:
            # Regional PPOs are not in PBP PlanArea; they serve their whole MA region (Landscape MA Region Code).
            for ssa in by_ma_region.get(p["ma_region_code"], []):
                pc.add((p["plan_key"], ssa))
    d.plan_county = [{"plan_year": year, "plan_key": k, "ssa_code": s} for k, s in sorted(pc)]

    # Medical benefits (S2).
    for section in ("b7", "b4", "b9"):
        for r in pbp.parse_section(_read(s2.paths[section]), section, s2.entry.vintage):
            if r["plan_key"] in plan_keys:
                d.pbp_benefit.append({"plan_year": year, **r})
    for kind, r in pbp.parse_inpatient(_read(s2.paths["b1a"]), s2.entry.vintage):
        if r["plan_key"] not in plan_keys:
            continue
        (d.inpatient if kind == "interval" else d.pbp_benefit).append({"plan_year": year, **r})

    # Part D (S3).
    pf: dict[str, str] = {}
    suppressed: set[str] = set()
    for r in spuf.parse_plan_info(_read(s3.paths["plan_info"])):
        if r["plan_key"] not in plan_keys:
            continue
        if r["suppressed"]:
            suppressed.add(r["plan_key"])
        else:
            pf.setdefault(r["plan_key"], r["formulary_id"])
    for p in d.plans:
        p["part_d_suppressed"] = p["plan_key"] in suppressed and p["plan_key"] not in pf
    d.plan_formulary = [{"plan_year": year, "plan_key": k, "formulary_id": f} for k, f in sorted(pf.items())]
    used = set(pf.values())
    d.formulary = [
        {"plan_year": year, **r}
        for r in spuf.parse_formulary(_read(s3.paths["formulary"]), s3.entry.vintage)
        if r["formulary_id"] in used
    ]
    d.tier_cost = [
        {"plan_year": year, **r}
        for r in spuf.parse_beneficiary_cost(_read(s3.paths["cost"]), s3.entry.vintage)
        if r["plan_key"] in plan_keys
    ]
    d.insulin = [
        {"plan_year": year, **r}
        for r in spuf.parse_insulin(_read(s3.paths["insulin"]), s3.entry.vintage)
        if r["plan_key"] in plan_keys
    ]

    params = spec["params"]["part_d"]
    d.part_d_params = {
        "plan_year": year,
        "std_deductible_cents": int(params["std_deductible_cents"]),
        "oop_threshold_cents": int(params["oop_threshold_cents"]),
        "src_ref": src_ref("S6", str(params["vintage"]), "part_d_params", url=params["citation"]),
    }
    return d


def _insert(conn: Connection, table: Table, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    batch: list[dict[str, Any]] = []
    for r in rows:
        batch.append(r)
        if len(batch) >= BATCH:
            conn.execute(insert(table), batch)
            n += len(batch)
            batch = []
    if batch:
        conn.execute(insert(table), batch)
        n += len(batch)
    return n


def swap_year(conn: Connection, data: YearData) -> dict[str, int]:
    """Replace this year's plan data (and the county table) inside the caller's transaction."""
    counts: dict[str, int] = {}
    for t in YEAR_TABLES:
        conn.execute(delete(t).where(t.c.plan_year == data.year))
    conn.execute(delete(m.county))
    counts["county"] = _insert(conn, m.county, data.counties)
    for t in YEAR_TABLES:
        counts[t.name] = _insert(conn, t, data.rows_for(t))
    return counts


def record_runs(conn: Connection, year: int, fetched: dict[str, Fetched], counts: dict[str, int], status: str) -> None:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    for sid, f in fetched.items():
        conn.execute(
            insert(m.ingest_run).values(
                plan_year=year,
                source_id=sid,
                url=f.entry.url,
                vintage=f.entry.vintage,
                # Range-read sources have no whole-file hash: store the hash of the sorted member hashes.
                sha256=f.entry.sha256 or sha256_bytes("".join(sorted(f.entry.members.values())).encode()),
                row_count=sum(counts.values()),
                status=status,
                started_at=now,
                finished_at=now,
            )
        )
