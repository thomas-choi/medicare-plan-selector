"""External lookups without identity (DESIGN §2): RxNav (drug name → RxCUI) and NPPES (doctor → NPI).

Only the drug or doctor name is sent, never a session or user identifier. Results are cached in process memory
only (no disk, no DB), so No-save mode holds nothing user-linked. Clients make at most one request per second.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx

RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"
NPPES_BASE = "https://npiregistry.cms.hhs.gov/api/"


class LookupError_(RuntimeError):
    pass


class _LRU:
    def __init__(self, size: int = 512) -> None:
        self._d: OrderedDict[str, Any] = OrderedDict()
        self._size = size
        self._lock = threading.Lock()

    def get(self, k: str) -> Any:
        with self._lock:
            if k in self._d:
                self._d.move_to_end(k)
                return self._d[k]
            return None

    def put(self, k: str, v: Any) -> None:
        with self._lock:
            self._d[k] = v
            self._d.move_to_end(k)
            while len(self._d) > self._size:
                self._d.popitem(last=False)


class _Throttled:
    def __init__(self, client: httpx.Client | None, min_interval_s: float) -> None:
        self._client = client or httpx.Client(timeout=15)
        self._min = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0

    def get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        with self._lock:
            wait = self._last + self._min - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        try:
            return self._client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise LookupError_(type(e).__name__) from e


@dataclass(frozen=True)
class DrugCandidate:
    rxcui: str
    name: str
    tty: str


class RxNavClient:
    def __init__(self, client: httpx.Client | None = None, base: str = RXNAV_BASE, min_interval_s: float = 1.0):
        self._http = _Throttled(client, min_interval_s)
        self._base = base.rstrip("/")
        self._cache = _LRU()

    def search(self, name: str, limit: int = 8) -> list[DrugCandidate]:
        key = name.strip().lower()
        if not key:
            return []
        hit = self._cache.get(key)
        if hit is not None:
            return list(hit)[:limit]
        r = self._http.get(f"{self._base}/drugs.json", {"name": key})
        if r.status_code != 200:
            raise LookupError_(f"RxNav HTTP {r.status_code}")
        out: list[DrugCandidate] = []
        for group in (r.json().get("drugGroup") or {}).get("conceptGroup") or []:
            if group.get("tty") not in ("SCD", "SBD", "GPCK", "BPCK"):
                continue
            for c in group.get("conceptProperties") or []:
                out.append(DrugCandidate(str(c["rxcui"]), str(c.get("name", ""))[:200], group["tty"]))
        out.sort(key=lambda c: (c.tty not in ("SCD", "GPCK"), c.name))
        self._cache.put(key, out)
        return out[:limit]


@dataclass(frozen=True)
class ProviderCandidate:
    npi: str
    name: str
    specialty: str
    city: str
    state: str


class NppesClient:
    def __init__(self, client: httpx.Client | None = None, base: str = NPPES_BASE, min_interval_s: float = 1.0):
        self._http = _Throttled(client, min_interval_s)
        self._base = base
        self._cache = _LRU()

    def search(self, last_name: str, first_name: str = "", state: str = "", limit: int = 5) -> list[ProviderCandidate]:
        key = f"{last_name}|{first_name}|{state}".lower()
        hit = self._cache.get(key)
        if hit is not None:
            return list(hit)
        params: dict[str, Any] = {"version": "2.1", "last_name": last_name, "limit": limit}
        if first_name:
            params["first_name"] = first_name
        if state:
            params["state"] = state
        r = self._http.get(self._base, params)
        if r.status_code != 200:
            raise LookupError_(f"NPPES HTTP {r.status_code}")
        out: list[ProviderCandidate] = []
        for res in r.json().get("results") or []:
            basic = res.get("basic") or {}
            tax: dict[str, Any] = next((t for t in res.get("taxonomies") or [] if t.get("primary")), {})
            addr: dict[str, Any] = next(
                (a for a in res.get("addresses") or [] if a.get("address_purpose") == "LOCATION"), {}
            )
            nm = " ".join(x for x in (basic.get("first_name"), basic.get("last_name")) if x) or basic.get(
                "organization_name", ""
            )
            out.append(
                ProviderCandidate(
                    str(res.get("number", "")),
                    str(nm)[:120],
                    str(tax.get("desc", ""))[:120],
                    str(addr.get("city", ""))[:64],
                    str(addr.get("state", ""))[:2],
                )
            )
        self._cache.put(key, out)
        return out
