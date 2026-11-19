"""External lookups without identity (DESIGN §2): RxNav (drug name → RxCUI) and NPPES (doctor → NPI).

Only the drug or doctor name is sent, never a session or user identifier. Results are cached in process memory
only (no disk, no DB), so No-save mode holds nothing user-linked. Clients make at most one request per second.
"""

from __future__ import annotations

import re
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


# Lookups answer an interactive search box: fail within seconds (a host without outbound internet otherwise
# leaves the UI waiting with no feedback), never the 15 s+ of a blocked connect.
LOOKUP_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


class _Throttled:
    def __init__(self, client: httpx.Client | None, min_interval_s: float) -> None:
        self._client = client or httpx.Client(timeout=LOOKUP_TIMEOUT)
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


@dataclass(frozen=True)
class DrugSearch:
    """`matched_as` is set when the results come from a fallback query, so the UI can say what it searched for."""

    candidates: list[DrugCandidate]
    matched_as: str | None = None
    how: str = "exact"  # exact | ingredient | approximate | none


DRUG_TTYS = ("SCD", "SBD", "GPCK", "BPCK")
# Words people type after the drug name ("tamsulosin 0.4 mg capsule"). RxNav `drugs.json` matches names, not
# strengths or dose forms, so a query that includes them finds nothing (the root cause of the "no response" report).
_STRENGTH = re.compile(r"^\d+(?:[.,]\d+)?(?:mg|mcg|g|ml|%|iu|units?|meq)?$")
_FORM_WORDS = frozenset(
    [
        "mg",
        "mcg",
        "g",
        "ml",
        "iu",
        "unit",
        "units",
        "meq",
        "%",
        "oral",
        "tab",
        "tabs",
        "tablet",
        "tablets",
        "cap",
        "caps",
        "capsule",
        "capsules",
        "er",
        "xr",
        "xl",
        "sr",
        "dr",
        "ir",
        "ec",
        "extended",
        "delayed",
        "immediate",
        "release",
        "solution",
        "suspension",
        "liquid",
        "injection",
        "inhaler",
        "patch",
        "cream",
        "ointment",
        "chewable",
        "dispersible",
        "pen",
        "vial",
        "each",
        "per",
        "hcl",
        "hydrochloride",
    ]
)


def normalize_drug_query(q: str) -> str:
    """Lowercase, collapse whitespace and split glued strengths ("0.4mg" -> "0.4 mg")."""
    q = re.sub(r"(\d)(mg|mcg|ml|g|iu|meq)\b", r"\1 \2", q.strip().lower())
    return " ".join(q.split())


def ingredient_query(q: str) -> str:
    """The name part of a query: drops strengths, units and dose-form words."""
    words = [w for w in normalize_drug_query(q).split() if not _STRENGTH.match(w) and w not in _FORM_WORDS]
    return " ".join(words)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", s.lower()))


def rank_candidates(cands: list[DrugCandidate], query: str) -> list[DrugCandidate]:
    """Best match first: most query words (strength, form) in the name, then single-ingredient, then generic
    (SCD/GPCK) before brand, then name. "tamsulosin 0.4 mg capsule" puts RxCUI 863669 first."""
    q = _tokens(normalize_drug_query(query))

    def key(c: DrugCandidate) -> tuple[int, int, bool, str]:
        return (-len(q & _tokens(c.name)), c.name.count(" / "), c.tty not in ("SCD", "GPCK"), c.name)

    return sorted(cands, key=key)


class RxNavClient:
    """RxNorm REST (S10). NLM asks for at most 20 requests/second per IP; the default spacing of 0.1 s per process
    stays well under that while letting one search make its 1-4 fallback calls without a visible delay."""

    def __init__(self, client: httpx.Client | None = None, base: str = RXNAV_BASE, min_interval_s: float = 0.1):
        self._http = _Throttled(client, min_interval_s)
        self._base = base.rstrip("/")
        self._cache = _LRU()

    def search(self, name: str, limit: int = 8) -> list[DrugCandidate]:
        return self.find(name, limit).candidates

    def find(self, name: str, limit: int = 8) -> DrugSearch:
        """Exact name search, then the ingredient name alone, then RxNav's approximate match (typos)."""
        key = normalize_drug_query(name)
        if not key:
            return DrugSearch([], None, "none")
        hit = self._cache.get(key)
        if hit is None:
            hit = self._find_uncached(key)
            self._cache.put(key, hit)
        res: DrugSearch = hit
        return DrugSearch(res.candidates[:limit], res.matched_as, res.how)

    def _find_uncached(self, key: str) -> DrugSearch:
        out = self._drugs(key)
        if out:
            return DrugSearch(rank_candidates(out, key), None, "exact")
        base = ingredient_query(key)
        if base and base != key and len(base) >= 2:
            out = self._drugs(base)
            if out:
                return DrugSearch(rank_candidates(out, key), base, "ingredient")
        out = self._approximate(key)
        if out:
            return DrugSearch(rank_candidates(out, key), out[0].name, "approximate")
        return DrugSearch([], None, "none")

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        r = self._http.get(f"{self._base}/{path}", params)
        if r.status_code != 200:
            raise LookupError_(f"RxNav HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as e:
            raise LookupError_("RxNav returned non-JSON") from e
        return data if isinstance(data, dict) else {}

    def _drugs(self, name: str) -> list[DrugCandidate]:
        out: list[DrugCandidate] = []
        for group in (self._get_json("drugs.json", {"name": name}).get("drugGroup") or {}).get("conceptGroup") or []:
            if group.get("tty") not in DRUG_TTYS:
                continue
            for c in group.get("conceptProperties") or []:
                out.append(DrugCandidate(str(c["rxcui"]), str(c.get("name", ""))[:200], group["tty"]))
        return out

    def _approximate(self, term: str, max_concepts: int = 3) -> list[DrugCandidate]:
        data = self._get_json("approximateTerm.json", {"term": term, "maxEntries": 10})
        rxcuis: list[str] = []
        for c in (data.get("approximateGroup") or {}).get("candidate") or []:
            rx = str(c.get("rxcui") or "")
            if rx and rx not in rxcuis:
                rxcuis.append(rx)
        out: list[DrugCandidate] = []
        for rx in rxcuis[:max_concepts]:
            props = self._get_json(f"rxcui/{rx}/properties.json", {}).get("properties") or {}
            if props.get("tty") in DRUG_TTYS:
                out.append(DrugCandidate(str(props["rxcui"]), str(props.get("name", ""))[:200], str(props["tty"])))
        return out


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
