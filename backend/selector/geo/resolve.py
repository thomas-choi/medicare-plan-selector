"""ZIP → county resolution with fallbacks (DESIGN §3 S12, HUD-API-SETUP.md).

Order: `zip_county_cache` (filled by `selector hud preload`, `selector hud load-file` or earlier lookups) →
HUD API when `HUD_API_TOKEN` is set → no mapping, in which case the caller offers a county picker for the state.
CMS plan data is keyed by SSA county code, so each FIPS is joined to `county` (several SSA codes can share one).
In No-save mode an API result is **not** written to the cache (the write guard would refuse it anyway).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, select

from selector import models as m
from selector.geo.ct_regions import PICK_NOTE, legacy_fips
from selector.geo.hud import ZIP_RE, HudClient, HudError, ZipCounty, cached_zip_counties, store_zip_counties

log = logging.getLogger(__name__)


@dataclass
class CountyOption:
    ssa_code: str
    fips: str | None
    state: str | None
    state_name: str
    name: str
    res_ratio: float | None
    fips_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ssa_code": self.ssa_code,
            "fips": self.fips,
            "state": self.state,
            "state_name": self.state_name,
            "county": self.name,
            "res_ratio": self.res_ratio,
            "fips_status": self.fips_status,
        }


@dataclass
class LocationResult:
    zip: str
    counties: list[CountyOption] = field(default_factory=list)
    source: str = "none"  # cache | hud_api | none
    note: str | None = None


def _counties_for(conn: Connection, zc: list[ZipCounty]) -> list[CountyOption]:
    """SSA counties for HUD rows. A Connecticut planning-region FIPS becomes its legacy county or counties
    (DESIGN v0.5 B6); a region spanning several keeps the HUD ratio on each, since HUD does not split it. A `retired`
    SSA area is never returned (B6.1)."""
    out: list[CountyOption] = []
    seen: set[str] = set()
    for z in zc:
        for fips in legacy_fips(z.fips):
            q = select(m.county).where(m.county.c.fips == fips, m.county.c.fips_status != "retired")
            rows = conn.execute(q.order_by(m.county.c.ssa_code))
            for r in rows.mappings():
                if r["ssa_code"] in seen:
                    continue
                seen.add(r["ssa_code"])
                out.append(
                    CountyOption(
                        r["ssa_code"],
                        r["fips"],
                        r["state"],
                        r["state_name"],
                        r["name"],
                        float(z.res_ratio),
                        r["fips_status"],
                    )
                )
    return out


def _pick_note(zc: list[ZipCounty]) -> str | None:
    return PICK_NOTE if any(len(legacy_fips(z.fips)) > 1 for z in zc) else None


def resolve_zip(
    conn: Connection,
    zip_code: str,
    *,
    hud: HudClient | None,
    may_write_cache: bool,
) -> LocationResult:
    if not ZIP_RE.match(zip_code or ""):
        raise ValueError("ZIP must be 5 digits")
    cached = cached_zip_counties(conn, zip_code)
    if cached:
        return LocationResult(zip_code, _counties_for(conn, cached), "cache", _pick_note(cached))
    if hud is not None:
        try:
            rows = hud.zip_counties(zip_code)
        except HudError as e:
            log.warning("hud lookup failed: %s", type(e).__name__)
            rows = []
        if rows:
            if may_write_cache:
                store_zip_counties(conn, rows)
            return LocationResult(zip_code, _counties_for(conn, rows), "hud_api", _pick_note(rows))
    return LocationResult(
        zip_code,
        [],
        "none",
        "This ZIP code isn't in our ZIP→county table yet. Pick your state and county instead.",
    )


def counties_in_state(conn: Connection, state: str) -> list[CountyOption]:
    """County picker fallback: every county CMS lists for a 2-letter state code, except retired SSA areas (no FIPS
    county today, e.g. Alaska's Valdez-Cordova; DESIGN v0.5 B6)."""
    rows = conn.execute(
        select(m.county)
        .where(m.county.c.state == state.upper(), m.county.c.fips_status != "retired")
        .order_by(m.county.c.name, m.county.c.ssa_code)
    ).mappings()
    return [
        CountyOption(r["ssa_code"], r["fips"], r["state"], r["state_name"], r["name"], None, r["fips_status"])
        for r in rows
    ]
