"""Provider-directory plan data (addendum A3.5): the curated endpoint list and the InsurancePlan → plan_key map.

`selector directories sync --year 2027` (ingest role) loads sources/directories.yaml into `directory_endpoint`
and, for each public endpoint, reads every `InsurancePlan` and stores the plans it can match to our `plan_key`
with their network references in `insurance_plan_map`. This is plan data with no user link. The API reads both
tables (read-only) when it checks a doctor's listing.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import Connection, Engine, delete, insert, select

from selector import models as m
from selector.cost.engine import PlanInfo
from selector.network import (
    TIMEOUT,
    USER_AGENT,
    Endpoint,
    FhirDirectory,
    HostThrottle,
    PlanDirectory,
    map_insurance_plan,
)

log = logging.getLogger(__name__)


def seed_endpoints(conn: Connection, endpoints: Iterable[Endpoint], notes: dict[str, str], verified_at: str) -> int:
    conn.execute(delete(m.directory_endpoint))
    rows = [
        {
            "id": e.id, "name": e.name, "org_patterns": list(e.org_patterns),
            "contract_prefixes": list(e.contract_prefixes), "base_url": e.base_url, "auth": e.auth,
            "plan_id_system": e.plan_id_system, "plan_id_format": e.plan_id_format, "npi_search": e.npi_search,
            "notes": (notes.get(e.id) or "")[:1024] or None, "verified_at": dt.date.fromisoformat(verified_at),
        }
        for e in endpoints
    ]  # fmt: skip
    if rows:
        conn.execute(insert(m.directory_endpoint), rows)
    return len(rows)


def load_endpoints(conn: Connection) -> dict[str, Endpoint]:
    return {r["id"]: Endpoint.from_mapping(r) for r in conn.execute(select(m.directory_endpoint)).mappings()}


@dataclass
class SyncResult:
    endpoint_id: str
    seen: int
    mapped: int
    error: str | None = None


def sync_endpoint(
    engine: Engine,
    year: int,
    ep: Endpoint,
    *,
    http: httpx.Client | None = None,
    min_interval_s: float = 1.0,
    max_pages: int = 200,
) -> SyncResult:
    """Replace this endpoint's `insurance_plan_map` rows for `year` with what its InsurancePlan resources say."""
    if not ep.usable:
        return SyncResult(ep.id, 0, 0, f"auth={ep.auth}: not called")
    with engine.connect() as c:
        known = set(c.execute(select(m.plan.c.plan_key).where(m.plan.c.plan_year == year)).scalars())
    client = http or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    fhir = FhirDirectory(ep, client, HostThrottle(min_interval_s))
    found: dict[str, dict[str, Any]] = {}
    seen = 0
    today = dt.date.today()
    try:
        for res in fhir.insurance_plans(max_pages=max_pages):
            seen += 1
            mapped = map_insurance_plan(ep, res)
            if mapped is None or mapped[0] not in known:
                continue
            key, ip_id, refs = mapped
            new = {"plan_year": year, "plan_key": key, "endpoint_id": ep.id, "insurance_plan_id": ip_id,
                   "network_refs": [], "fetched_at": today}  # fmt: skip
            row = found.setdefault(key, new)
            row["network_refs"] = sorted(set(row["network_refs"]) | set(refs))
    except Exception as e:  # noqa: BLE001 - keep the old map for this endpoint on any failure
        log.warning("directory sync %s failed: %s", ep.id, type(e).__name__)
        return SyncResult(ep.id, seen, 0, type(e).__name__)
    with engine.begin() as c:
        ipm = m.insurance_plan_map
        c.execute(delete(ipm).where(ipm.c.plan_year == year, ipm.c.endpoint_id == ep.id))
        if found:
            c.execute(insert(ipm), list(found.values()))
    return SyncResult(ep.id, seen, len(found))


def plan_directories(
    conn: Connection, year: int, plans: list[PlanInfo]
) -> tuple[list[PlanDirectory], dict[str, Endpoint]]:
    """Each plan's endpoint and network references: from `insurance_plan_map`, else by organization name."""
    endpoints = load_endpoints(conn)
    keys = [p.plan_key for p in plans if p.category != "PDP"]
    ipm = m.insurance_plan_map
    mapped: dict[str, Any] = {}
    if keys:
        mapped = {
            r["plan_key"]: r
            for r in conn.execute(select(ipm).where(ipm.c.plan_year == year, ipm.c.plan_key.in_(keys))).mappings()
        }
    out: list[PlanDirectory] = []
    for p in plans:
        if p.category == "PDP":
            out.append(PlanDirectory(p.plan_key, "PDP", None))
            continue
        r = mapped.get(p.plan_key)
        if r is not None and r["endpoint_id"] in endpoints:
            out.append(PlanDirectory(p.plan_key, p.category, r["endpoint_id"], frozenset(r["network_refs"]), True))
            continue
        ep = next((e for e in endpoints.values() if e.matches_org(p.org_marketing_name, p.plan_key[:5])), None)
        out.append(PlanDirectory(p.plan_key, p.category, ep.id if ep else None))
    return out, endpoints
