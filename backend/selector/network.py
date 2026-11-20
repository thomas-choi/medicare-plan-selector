"""Doctor listing checks against carriers' public provider directories (design v0.4 addendum A3).

CMS-9115-F requires every MA organization to publish a Provider Directory API without user authentication; most
follow HL7 Da Vinci PDex Plan-Net, where `InsurancePlan` carries the CMS plan id and its network `Organization`s,
and `PractitionerRole` ties a practitioner (by NPI) to networks through the `network-reference` extension.

What we can honestly say is a *listing status*, never "covered" (directories are often out of date):

| status | meaning |
|---|---|
| listed | the NPI has a PractitionerRole in a network linked to this plan's InsurancePlan |
| not_listed | directory reachable, plan matched, NPI not linked to any of its networks |
| unknown | directory reachable but the plan or the NPI couldn't be matched completely |
| unavailable | no public endpoint, needs registration, timeout or error |
| original_medicare / opted_out | Original Medicare rows: any doctor who accepts Medicare / on the CMS opt-out list |
| no_npi | a doctor typed by name only (pick them from the search to check) |

Privacy (addendum A3.5): only an NPI (the doctor's public identifier) and carrier-side ids leave the server;
never the user's ZIP, drugs or session. Results are cached in process memory only (24 h), keyed by
(endpoint, NPI), with nothing that ties them to a session.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

log = logging.getLogger(__name__)

NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"
NETWORK_EXT = "http://hl7.org/fhir/us/davinci-pdex-plan-net/StructureDefinition/network-reference"
USER_AGENT = "medicare-plan-selector (+https://github.com/thomas-choi/medicare-plan-selector)"
TIMEOUT = httpx.Timeout(8.0, connect=4.0)  # interactive checks
# Admin sync only: some directories take 12-15 s per InsurancePlan page (UHC, 2026-11-19).
SYNC_TIMEOUT = httpx.Timeout(90.0, connect=10.0)
CACHE_TTL_S = 24 * 3600
ROLE_PAGE = 100
MAX_ROLE_PAGES = 5
MAX_FILTER_REFS = 40  # above this, page through all roles instead of a long `network=` filter
SOURCES_FILE = Path(__file__).resolve().parents[2] / "sources" / "directories.yaml"

STATUSES = ("listed", "not_listed", "unknown", "unavailable", "original_medicare", "opted_out", "no_npi")
CHECK_NOTE = "Directory listings can be out of date. Call the plan to confirm."


def day_text(d: dt.date) -> str:
    return f"{d:%b} {d.day}"


def status_text(status: str, checked: dt.date | None) -> str:
    """The exact UI wording of addendum A3.3."""
    when = f" (checked {day_text(checked)})" if checked else ""
    return {
        "listed": f"✓ Listed in the plan's directory{when}. Call to confirm.",
        "not_listed": f"Not found in the plan's directory{when}. May be out of network: call the plan.",
        "unknown": "Couldn't check this plan's directory. Call the plan.",
        "unavailable": "This plan's directory can't be checked automatically. Call the plan.",
        "original_medicare": f"Original Medicare: any doctor who accepts Medicare. Not on the opt-out list{when}.",
        "opted_out": "Opted out of Medicare: you'd pay this doctor yourself.",
        "no_npi": "Pick this doctor from the search to check plan directories.",
    }[status]


def norm_ref(ref: str) -> str:
    """'https://host/api/Organization/abc' and 'Organization/abc' → 'Organization/abc'."""
    parts = ref.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else ref


# --------------------------------------------------------------------------------------------- configuration


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str
    base_url: str
    auth: str = "none"
    org_patterns: tuple[str, ...] = ()
    contract_prefixes: tuple[str, ...] = ()
    plan_id_system: str = ""
    plan_id_format: str = ""
    npi_search: str = "supported"

    @property
    def usable(self) -> bool:
        return self.auth == "none" and bool(self.base_url)

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or self.base_url

    def matches_org(self, org_name: str, contract_id: str) -> bool:
        o = org_name.lower()
        return any(p.lower() in o for p in self.org_patterns) or contract_id in self.contract_prefixes

    def plan_key_for(self, identifiers: Iterable[dict[str, Any]]) -> str | None:
        if not self.plan_id_format:
            return None
        rx = re.compile(self.plan_id_format)
        for ident in identifiers:
            if self.plan_id_system and ident.get("system") != self.plan_id_system:
                continue
            m = rx.match(str(ident.get("value", "")).strip())
            if m:
                return f"{m['contract']}_{int(m['plan']):03d}_{int(m['segment'])}"
        return None

    @classmethod
    def from_mapping(cls, d: Any) -> Endpoint:
        return cls(
            id=str(d["id"]),
            name=str(d["name"]),
            base_url=str(d["base_url"]).rstrip("/"),
            auth=str(d.get("auth") or "none"),
            org_patterns=tuple(d.get("org_patterns") or ()),
            contract_prefixes=tuple(d.get("contract_prefixes") or ()),
            plan_id_system=str(d.get("plan_id_system") or ""),
            plan_id_format=str(d.get("plan_id_format") or ""),
            npi_search=str(d.get("npi_search") or "supported"),
        )


@dataclass(frozen=True)
class OptOutConfig:
    url: str
    vintage: str
    source: str = "S14"


def load_sources(path: Path = SOURCES_FILE) -> tuple[list[Endpoint], OptOutConfig | None, dict[str, Any]]:
    spec: dict[str, Any] = yaml.safe_load(path.read_text())
    eps = [Endpoint.from_mapping(e) for e in spec.get("endpoints", [])]
    oo = spec.get("optout")
    cfg = None
    if oo:
        cfg = OptOutConfig(str(oo["url"]).format(dataset_id=oo["dataset_id"]), str(oo["vintage"]), str(oo["source"]))
    return eps, cfg, spec


@dataclass(frozen=True)
class PlanDirectory:
    """What the checker needs about one plan: its endpoint (if any) and its network references."""

    plan_key: str
    category: str
    endpoint_id: str | None
    network_refs: frozenset[str] = frozenset()
    mapped: bool = False  # an insurance_plan_map row exists


@dataclass(frozen=True)
class DoctorRef:
    name: str
    npi: str | None
    must_keep: bool = False


@dataclass(frozen=True)
class Listing:
    status: str
    checked_at: dt.date | None
    source: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, doc: DoctorRef) -> dict[str, Any]:
        return {
            "npi": doc.npi,
            "name": doc.name,
            "must_keep": doc.must_keep,
            "status": self.status,
            "text": status_text(self.status, self.checked_at),
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "source": self.source,
        }


# --------------------------------------------------------------------------------------------- HTTP clients


class DirectoryError(RuntimeError):
    pass


class _TTLCache:
    def __init__(self, size: int = 2048, ttl_s: float = CACHE_TTL_S, clock: Callable[[], float] = time.monotonic):
        self._d: OrderedDict[tuple[str, str], tuple[float, Any]] = OrderedDict()
        self._size, self._ttl, self._clock = size, ttl_s, clock
        self._lock = threading.Lock()

    def get(self, k: tuple[str, str]) -> Any:
        with self._lock:
            hit = self._d.get(k)
            if hit is None or self._clock() - hit[0] > self._ttl:
                self._d.pop(k, None)
                return None
            self._d.move_to_end(k)
            return hit[1]

    def put(self, k: tuple[str, str], v: Any) -> None:
        with self._lock:
            self._d[k] = (self._clock(), v)
            self._d.move_to_end(k)
            while len(self._d) > self._size:
                self._d.popitem(last=False)


class HostThrottle:
    """At most one request per `min_interval_s` per host (addendum A3.4: 1 request/second/host)."""

    def __init__(self, min_interval_s: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self._min = min_interval_s
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._sleep = sleep

    def wait(self, host: str) -> None:
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            gap = self._last.get(host, 0.0) + self._min - time.monotonic()
            if gap > 0:
                self._sleep(gap)
            self._last[host] = time.monotonic()


@dataclass
class RoleResult:
    found: bool  # at least one Practitioner with this NPI
    networks: frozenset[str]
    complete: bool  # every role page was read
    within: frozenset[str] | None = None  # the `network=` filter used (None = all of the practitioner's roles)

    def covers(self, refs: frozenset[str]) -> bool:
        """Can this (cached) result answer a question about `refs`?"""
        return self.complete and (self.within is None or refs <= self.within)


class FhirDirectory:
    """Plan-Net reads for one endpoint. Sends only an NPI, practitioner ids and network ids."""

    def __init__(self, ep: Endpoint, http: httpx.Client, throttle: HostThrottle) -> None:
        self.ep, self._http, self._throttle = ep, http, throttle

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if urlparse(url).hostname != self.ep.host:
            raise DirectoryError("refusing to follow a link to another host")
        self._throttle.wait(self.ep.host)
        try:
            r = self._http.get(url, params=params, headers={"Accept": "application/fhir+json"})
        except httpx.HTTPError as e:
            raise DirectoryError(type(e).__name__) from e
        if r.status_code != 200:
            raise DirectoryError(f"HTTP {r.status_code}")
        try:
            body: dict[str, Any] = r.json()
        except ValueError as e:
            raise DirectoryError("not JSON") from e
        if body.get("resourceType") != "Bundle":
            raise DirectoryError(f"unexpected {body.get('resourceType')}")
        return body

    @staticmethod
    def _next(bundle: dict[str, Any]) -> str | None:
        return next((str(link["url"]) for link in bundle.get("link") or [] if link.get("relation") == "next"), None)

    def practitioner_ids(self, npi: str) -> list[str]:
        b = self._get(f"{self.ep.base_url}/Practitioner", {"identifier": f"{NPI_SYSTEM}|{npi}"})
        return [
            str(e["resource"]["id"])
            for e in b.get("entry") or []
            if e.get("resource", {}).get("resourceType") == "Practitioner" and e["resource"].get("id")
        ]

    def role_networks(self, npi: str, filter_refs: frozenset[str] = frozenset()) -> RoleResult:
        ids = self.practitioner_ids(npi)
        if not ids:
            return RoleResult(False, frozenset(), True)
        params: dict[str, Any] = {"practitioner": ",".join(f"Practitioner/{i}" for i in ids), "_count": ROLE_PAGE}
        within = None
        if filter_refs and len(filter_refs) <= MAX_FILTER_REFS:
            within = filter_refs
            params["network"] = ",".join(sorted(filter_refs))
        nets: set[str] = set()
        url: str | None = f"{self.ep.base_url}/PractitionerRole"
        pages = 0
        while url and pages < MAX_ROLE_PAGES:
            b = self._get(url, params if pages == 0 else None)
            pages += 1
            for e in b.get("entry") or []:
                res = e.get("resource") or {}
                if res.get("resourceType") != "PractitionerRole":
                    continue
                for ext in res.get("extension") or []:
                    if ext.get("url") == NETWORK_EXT and (ref := (ext.get("valueReference") or {}).get("reference")):
                        nets.add(norm_ref(str(ref)))
                for n in res.get("network") or []:  # some servers use a plain `network` element
                    if ref := n.get("reference"):
                        nets.add(norm_ref(str(ref)))
            url = self._next(b)
        return RoleResult(True, frozenset(nets), url is None, within)

    def insurance_plans(self, max_pages: int = 200) -> Iterator[dict[str, Any]]:
        """Every InsurancePlan resource, following `next` links (admin sync only)."""
        url: str | None = f"{self.ep.base_url}/InsurancePlan"
        # `_elements` keeps pages small (UHC: 3.6 MB → 120 kB per 100 plans); servers that ignore it still work.
        params: dict[str, Any] | None = {"_count": 100, "_elements": "identifier,network,plan"}
        pages = 0
        while url and pages < max_pages:
            b = self._get(url, params)
            params, pages = None, pages + 1
            for e in b.get("entry") or []:
                res = e.get("resource") or {}
                if res.get("resourceType") == "InsurancePlan":
                    yield res
            url = self._next(b)


class OptOutClient:
    """CMS Opt Out Affidavits (S14) on data.cms.gov: is this NPI opted out of Medicare today? Sends the NPI only."""

    def __init__(self, cfg: OptOutConfig, http: httpx.Client, throttle: HostThrottle) -> None:
        self.cfg, self._http, self._throttle = cfg, http, throttle

    def opted_out(self, npi: str, today: dt.date) -> bool:
        self._throttle.wait(urlparse(self.cfg.url).hostname or "data.cms.gov")
        try:
            r = self._http.get(self.cfg.url, params={"filter[NPI]": npi, "size": 5})
        except httpx.HTTPError as e:
            raise DirectoryError(type(e).__name__) from e
        if r.status_code != 200:
            raise DirectoryError(f"HTTP {r.status_code}")
        for row in r.json() or []:
            if str(row.get("NPI")) != npi:
                continue
            start, end = _date(row.get("Optout Effective Date")), _date(row.get("Optout End Date"))
            if (start is None or start <= today) and (end is None or end >= today):
                return True
        return False


def _date(v: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------- the checker


class DirectoryChecker:
    """`check()` returns `{plan_key: {npi: Listing}}` for MA plans (directories) and Original Medicare rows (PDPs
    and BASELINE: the opt-out list). Everything not answered within `budget_s` is `unavailable`."""

    def __init__(
        self,
        optout: OptOutConfig | None,
        *,
        http: httpx.Client | None = None,
        min_interval_s: float = 1.0,
        budget_s: float = 8.0,
        today: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self._http = http or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        self._throttle = HostThrottle(min_interval_s)
        self._optout = OptOutClient(optout, self._http, self._throttle) if optout else None
        self.optout_cfg = optout
        self._cache = _TTLCache()
        self.budget_s = budget_s
        self.today = today

    def _roles(self, ep: Endpoint, npi: str, refs: frozenset[str]) -> RoleResult:
        key = (ep.id, npi)
        hit = self._cache.get(key)
        if isinstance(hit, RoleResult) and hit.covers(refs):
            return hit
        res = FhirDirectory(ep, self._http, self._throttle).role_networks(npi, refs)
        if res.complete:
            self._cache.put(key, res)
        return res

    def _opted_out(self, npi: str, today: dt.date) -> bool:
        assert self._optout is not None
        key = ("optout", npi)
        hit = self._cache.get(key)
        if isinstance(hit, bool):
            return hit
        out = self._optout.opted_out(npi, today)
        self._cache.put(key, out)
        return out

    def check(
        self, doctors: list[DoctorRef], plans: list[PlanDirectory], endpoints: dict[str, Endpoint]
    ) -> dict[str, dict[str, Listing]]:
        today = self.today()
        npis = list(dict.fromkeys(d.npi for d in doctors if d.npi))
        out: dict[str, dict[str, Listing]] = {p.plan_key: {} for p in plans}
        if not npis or not plans:
            return out
        # One job per endpoint (NPIs in sequence, throttled per host) and one for the opt-out list; in parallel.
        by_ep: dict[str, list[PlanDirectory]] = {}
        original: list[PlanDirectory] = []
        for p in plans:
            if p.category in ("PDP", "BASELINE"):
                original.append(p)
            elif p.endpoint_id and p.endpoint_id in endpoints and endpoints[p.endpoint_id].usable:
                if p.mapped and p.network_refs:
                    by_ep.setdefault(p.endpoint_id, []).append(p)
                else:  # the carrier has a directory, but this plan isn't matched to one of its InsurancePlans
                    src = {"source": "S13", "endpoint": endpoints[p.endpoint_id].host, "row": p.plan_key}
                    for n in npis:
                        out[p.plan_key][n] = Listing("unknown", None, src)
            else:
                for n in npis:
                    out[p.plan_key][n] = Listing("unavailable", None)
        results: dict[tuple[str, str], RoleResult | bool | None] = {}
        lock = threading.Lock()

        def run_endpoint(ep: Endpoint, eplans: list[PlanDirectory]) -> None:
            refs = frozenset().union(*(p.network_refs for p in eplans))
            for n in npis:
                try:
                    r: RoleResult | None = self._roles(ep, n, refs)
                except DirectoryError as e:
                    log.warning("directory %s unavailable: %s", ep.id, e)
                    r = None
                with lock:
                    results[(ep.id, n)] = r

        def run_optout() -> None:
            for n in npis:
                try:
                    v: bool | None = self._opted_out(n, today)
                except DirectoryError as e:
                    log.warning("opt-out list unavailable: %s", e)
                    v = None
                with lock:
                    results[("optout", n)] = v

        pool = ThreadPoolExecutor(max_workers=len(by_ep) + 1, thread_name_prefix="directory")
        futs = [pool.submit(run_endpoint, endpoints[eid], ps) for eid, ps in by_ep.items()]
        if original and self._optout is not None:
            futs.append(pool.submit(run_optout))
        wait(futs, timeout=self.budget_s)
        pool.shutdown(wait=False, cancel_futures=True)
        with lock:
            done = dict(results)

        for eid, eplans in by_ep.items():
            ep = endpoints[eid]
            for p in eplans:
                for n in npis:
                    out[p.plan_key][n] = self._plan_status(ep, p, done.get((eid, n)), (eid, n) in done, today)
        for p in original:
            for n in npis:
                v = done.get(("optout", n))
                if self._optout is None or v is None:
                    out[p.plan_key][n] = Listing("unavailable", None)
                else:
                    src = {"source": self._optout.cfg.source, "vintage": self._optout.cfg.vintage, "row": "npi"}
                    out[p.plan_key][n] = Listing("opted_out" if v else "original_medicare", today, src)
        return out

    @staticmethod
    def _plan_status(
        ep: Endpoint, p: PlanDirectory, r: RoleResult | bool | None, answered: bool, today: dt.date
    ) -> Listing:
        src = {"source": "S13", "endpoint": ep.host, "row": p.plan_key}
        if not answered or not isinstance(r, RoleResult):
            return Listing("unavailable", None, src)
        if r.networks & p.network_refs:
            return Listing("listed", today, src)
        if not r.found:
            return Listing("not_listed" if ep.npi_search == "supported" else "unknown", today, src)
        return Listing("not_listed" if r.complete else "unknown", today, src)


# --------------------------------------------------------------------------------------------- admin sync


def map_insurance_plan(ep: Endpoint, res: dict[str, Any]) -> tuple[str, str, list[str]] | None:
    """(plan_key, InsurancePlan id, network refs) for one InsurancePlan resource, or None if it has no CMS id."""
    key = ep.plan_key_for(res.get("identifier") or [])
    if key is None:
        return None
    refs = {norm_ref(str(n["reference"])) for n in res.get("network") or [] if n.get("reference")}
    for pl in res.get("plan") or []:
        refs |= {norm_ref(str(n["reference"])) for n in pl.get("network") or [] if n.get("reference")}
    return key, str(res.get("id", ""))[:128], sorted(refs)
