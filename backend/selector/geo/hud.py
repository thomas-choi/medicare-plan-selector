"""HUD USPS ZIP crosswalk API client, `type=2` (zip-county). See docs/design/HUD-API-SETUP.md.

Documented (V): GET only, `Authorization: Bearer <token>`, JSON; response `data.results[]` with `geoid` (5-digit
FIPS) and `res_ratio`; 401 bad token, 403 dataset not enabled, 404 no data, 406 needs Accept: application/json.
Unverified (U): where year/quarter appear in the response — read from `data` when present, else from the request.
The client sends at most 1 request per second (our own limit) and never sends anything but the ZIP or state.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import Connection, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from selector import models as m

ZIP_RE = re.compile(r"^\d{5}$")


class HudError(RuntimeError):
    pass


class HudAuthError(HudError):
    """401/403: bad token or the USPS Crosswalk dataset isn't enabled for the account."""


@dataclass(frozen=True)
class ZipCounty:
    zip: str
    fips: str
    res_ratio: Decimal
    hud_year: int
    hud_quarter: int


class HudClient:
    def __init__(self, token: str, base_url: str, client: httpx.Client | None = None, min_interval_s: float = 1.0):
        if not token:
            raise HudAuthError("HUD_API_TOKEN is not set (see docs/design/HUD-API-SETUP.md)")
        self._token = token
        self._base = base_url
        self._client = client or httpx.Client(timeout=30)
        self._min_interval = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _get(self, query: str, year: int | None = None, quarter: int | None = None) -> list[ZipCounty]:
        params: dict[str, Any] = {"type": 2, "query": query}
        if year:
            params["year"] = year
        if quarter:
            params["quarter"] = quarter
        self._throttle()
        r = self._client.get(
            self._base,
            params=params,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )
        if r.status_code in (401, 403):
            raise HudAuthError(f"HUD API {r.status_code}: check the token and the USPS Crosswalk dataset")
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            raise HudError(f"HUD API status {r.status_code}")
        data = r.json().get("data", {})
        y = int(data.get("year") or year or 0)
        q = int(data.get("quarter") or quarter or 0)
        out = []
        for res in data.get("results", []):
            z = str(res.get("zip") or (query if ZIP_RE.match(query) else "")).zfill(5)
            geoid = str(res["geoid"]).zfill(5)
            out.append(ZipCounty(z, geoid, Decimal(str(res.get("res_ratio", 0))), y, q))
        return out

    def zip_counties(self, zip_code: str) -> list[ZipCounty]:
        if not ZIP_RE.match(zip_code):
            raise ValueError("ZIP must be 5 digits")
        return sorted(self._get(zip_code), key=lambda z: (-z.res_ratio, z.fips))

    def state_counties(self, state: str) -> list[ZipCounty]:
        if not re.fullmatch(r"[A-Z]{2}|All", state):
            raise ValueError("state must be a 2-letter code or 'All'")
        return self._get(state)


def cached_zip_counties(conn: Connection, zip_code: str) -> list[ZipCounty]:
    rows = conn.execute(select(m.zip_county_cache).where(m.zip_county_cache.c.zip == zip_code)).mappings()
    return sorted(
        (ZipCounty(r["zip"], r["fips"], r["res_ratio"], r["hud_year"], r["hud_quarter"]) for r in rows),
        key=lambda z: (-z.res_ratio, z.fips),
    )


def store_zip_counties(conn: Connection, rows: list[ZipCounty], today: dt.date | None = None) -> int:
    """Upsert into `zip_county_cache` (ZIP + county only; never linked to a user). Callers in No-save mode must
    not call this (the write guard enforces it)."""
    if not rows:
        return 0
    day = today or dt.date.today()
    stmt = mysql_insert(m.zip_county_cache).values(
        [
            {
                "zip": r.zip,
                "fips": r.fips,
                "res_ratio": r.res_ratio,
                "hud_year": r.hud_year,
                "hud_quarter": r.hud_quarter,
                "fetched_at": day,
            }
            for r in rows
        ]  # fmt: skip
    )
    stmt = stmt.on_duplicate_key_update(
        res_ratio=stmt.inserted.res_ratio,
        hud_year=stmt.inserted.hud_year,
        hud_quarter=stmt.inserted.hud_quarter,
        fetched_at=stmt.inserted.fetched_at,
    )
    conn.execute(stmt)
    return len(rows)
