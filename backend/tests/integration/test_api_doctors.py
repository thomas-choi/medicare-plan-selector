"""WP13 on the committed CMS fixtures (Maricopa): doctors with NPIs and must-keep (P5), `selector directories sync`
into the scratch schema, POST /api/providers/network, listing badges and the filter in POST /api/compare, and what
leaves the server (P10). Carrier directories and the opt-out list are respx mocks shaped like the 2026-11-19 calls."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import create_engine, text

from selector.directories import seed_endpoints, sync_endpoint
from selector.network import NETWORK_EXT, NPI_SYSTEM, DirectoryChecker, OptOutConfig, load_sources
from tests.api_support import SENTINEL_DOCTOR, SENTINEL_DRUG, SENTINEL_ZIP, client, sentinel_profile, start
from tests.nosave.test_api_nosave import user_counts

pytestmark = pytest.mark.infra

NPI_LISTED, NPI_OUT, NPI_OPTED = "1437170412", "1679052898", "1447580105"
OPTOUT = OptOutConfig("https://optout.example/data", "Opt Out 2026-09-01")
TODAY = dt.date(2026, 11, 19)
UHC_BASE = "https://flex.optum.com/fhirpublic/R4"
HUM_BASE = "https://fhir.humana.com/api"


def bundle(*res: dict[str, Any]) -> dict[str, Any]:
    return {"resourceType": "Bundle", "type": "searchset", "link": [], "entry": [{"resource": r} for r in res]}


def mock_directories(r: respx.MockRouter) -> None:
    # InsurancePlans: H0609_083_0 at UHC (network uN), H0028_028_0 + H5216_034_0 at Humana (network hN).
    r.get(f"{UHC_BASE}/InsurancePlan").respond(json=bundle(
        {"resourceType": "InsurancePlan", "id": "u1", "network": [{"reference": "Organization/uN"}],
         "identifier": [{"system": "urn:cms:medicare-advantage-contract", "value": "H0609083000"}]},
        {"resourceType": "InsurancePlan", "id": "commercial",
         "network": [{"reference": "Organization/c"}]}))  # fmt: skip
    r.get(f"{HUM_BASE}/InsurancePlan").respond(json=bundle(*[
        {"resourceType": "InsurancePlan", "id": f"h{i}", "network": [{"reference": f"{HUM_BASE}/Organization/hN"}],
         "identifier": [{"system": "https://fhir.humana.com/documentation/glossary/PlanId", "value": v}]}
        for i, v in enumerate(("H0028-028-000-2027", "H5216-034-000-2027", "H9999-001-000-2027"))]))  # fmt: skip
    for base, pid_prefix in ((UHC_BASE, "u"), (HUM_BASE, "h")):
        r.get(f"{base}/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_LISTED}"}).respond(
            json=bundle({"resourceType": "Practitioner", "id": f"{pid_prefix}L"})
        )
        r.get(f"{base}/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_OUT}"}).respond(json=bundle())
        r.get(f"{base}/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_OPTED}"}).respond(json=bundle())
    r.get(f"{UHC_BASE}/PractitionerRole").respond(json=bundle(
        {"resourceType": "PractitionerRole", "id": "x", "practitioner": {"reference": "Practitioner/uL"},
         "extension": [{"url": NETWORK_EXT, "valueReference": {"reference": "Organization/uN"}}]}))  # fmt: skip
    r.get(f"{HUM_BASE}/PractitionerRole").respond(json=bundle(
        {"resourceType": "PractitionerRole", "id": "y", "practitioner": {"reference": "Practitioner/hL"},
         "extension": [{"url": NETWORK_EXT,
                        "valueReference": {"reference": f"{HUM_BASE}/Organization/other"}}]}))  # fmt: skip
    r.get(OPTOUT.url, params={"filter[NPI]": NPI_OPTED}).respond(
        json=[{"NPI": NPI_OPTED, "Optout Effective Date": "2016-10-01", "Optout End Date": "2028-10-01"}]
    )
    r.get(OPTOUT.url).respond(json=[])


@pytest.fixture(scope="module")
def synced(fixture_db: dict[str, str]) -> dict[str, str]:
    """The fixture schema with directory_endpoint seeded and insurance_plan_map synced from the mocks."""
    eng = create_engine(fixture_db["ingest"])
    endpoints, _, spec = load_sources()
    with eng.begin() as c:
        seed_endpoints(c, endpoints, {}, str(spec["verified_at"]))
    with respx.mock(assert_all_called=False) as r:
        mock_directories(r)
        results = {ep.id: sync_endpoint(eng, 2027, ep, http=httpx.Client(), min_interval_s=0) for ep in endpoints}
    eng.dispose()
    assert results["uhc"].mapped == 1 and results["humana"].mapped == 2  # H9999 isn't a 2027 plan: skipped
    assert results["aetna"].error == "auth=app_key: not called"
    return fixture_db


def app(db: dict[str, str]) -> Any:
    c = client(db)
    c.app.state.msp.directory = DirectoryChecker(OPTOUT, http=httpx.Client(), min_interval_s=0,  # type: ignore[attr-defined]
                                                 today=lambda: TODAY)  # fmt: skip
    return c


@pytest.fixture
def mocked() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as r:
        mock_directories(r)
        yield r


DOCTORS = [
    {"name": "Ana Listed", "npi": NPI_LISTED, "must_keep": True, "specialty": "Internal Medicine", "city": "PHOENIX"},
    {"name": "Bo Elsewhere", "npi": NPI_OUT, "must_keep": False},
    {"name": "Cy Optedout", "npi": NPI_OPTED},
    {"name": "Typed Only"},
]


def _profile(**kw: Any) -> dict[str, Any]:
    return {"zip": "85004", "county_ssa": "03060", "county_name": "Maricopa", "state": "AZ", "providers": DOCTORS,
            **kw}  # fmt: skip


def test_sync_stores_plan_map(synced: dict[str, str]) -> None:
    eng = create_engine(synced["api"])
    with eng.connect() as c:
        rows = {r.plan_key: r for r in c.execute(text("SELECT * FROM insurance_plan_map WHERE plan_year=2027"))}
        n = c.execute(text("SELECT COUNT(*) FROM directory_endpoint")).scalar_one()
    eng.dispose()
    assert set(rows) == {"H0609_083_0", "H0028_028_0", "H5216_034_0"} and n >= 3
    assert rows["H0028_028_0"].endpoint_id == "humana"


def test_p5_npi_pick_round_trips_and_nosave_writes_nothing(synced: dict[str, str]) -> None:
    before = user_counts(synced["migrator"])
    c = app(synced)
    start(c)
    assert c.put("/api/profile", json=_profile()).status_code == 200
    prof = c.get("/api/session").json()["profile"]
    assert prof["providers"][0] == {"name": "Ana Listed", "npi": NPI_LISTED, "must_keep": True,
                                    "specialty": "Internal Medicine", "city": "PHOENIX"}  # fmt: skip
    assert prof["providers"][3]["npi"] is None and prof["providers"][3]["must_keep"] is False
    bad = _profile(providers=[{"name": "X", "npi": "123"}])
    assert c.put("/api/profile", json=bad).status_code == 422
    assert user_counts(synced["migrator"]) == before  # N1 extended: No-save wrote no user rows


def test_compare_badges_and_filter(synced: dict[str, str], mocked: respx.MockRouter) -> None:
    c = app(synced)
    start(c)
    canvas = c.post("/api/compare", json={"profile": _profile()}).json()["canvas"]
    rows = {r["plan_key"]: r for r in canvas["rows"]}

    def st(k: str) -> dict[str, str]:
        src = canvas["baseline"] if k == "BASELINE" else rows[k]
        return {d["name"]: d["status"] for d in src["doctors"]}

    assert st("H0609_083_0") == {"Ana Listed": "listed", "Bo Elsewhere": "not_listed", "Cy Optedout": "not_listed",
                                 "Typed Only": "no_npi"}  # fmt: skip
    assert st("H0028_028_0")["Ana Listed"] == "not_listed"  # Humana lists her only in another network
    assert st("H0028_077_0")["Ana Listed"] == "unknown"  # Humana plan without an InsurancePlan match
    assert st("R7220_001_0")["Ana Listed"] == "unknown"
    assert st("S4802_092_0") == {"Ana Listed": "original_medicare", "Bo Elsewhere": "original_medicare",
                                 "Cy Optedout": "opted_out", "Typed Only": "no_npi"}  # fmt: skip
    assert st("BASELINE")["Cy Optedout"] == "opted_out"
    listed = next(d for d in rows["H0609_083_0"]["doctors"] if d["status"] == "listed")
    assert listed["text"] == "✓ Listed in the plan's directory (checked Nov 19). Call to confirm."
    assert rows["H0609_083_0"]["rank"] is not None and rows["H0028_028_0"]["rank"] is not None  # badges only

    on = c.post("/api/compare", json={"profile": _profile(must_haves={"doctors_listed": True})}).json()["canvas"]
    by = {r["plan_key"]: r for r in on["rows"]}
    reason = by["H0028_028_0"]["dropped_reason"]
    assert reason == "Your doctor Ana Listed isn't in this plan's directory (checked Nov 19)."
    assert by["H0609_083_0"]["rank"] is not None and by["R7220_001_0"]["rank"] is not None  # unknown never drops
    assert on["baseline"]["rank"] is None and on["baseline"]["dropped_reason"] is None


def test_providers_network_endpoint(synced: dict[str, str], mocked: respx.MockRouter) -> None:
    c = app(synced)
    start(c)
    c.put("/api/profile", json=_profile())
    r = c.post("/api/providers/network", json={"npis": [NPI_LISTED], "plan_keys": ["H0609_083_0", "BASELINE"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["checked_at"] == "2026-11-19" and "Call the plan" in out["note"]
    assert out["results"]["H0609_083_0"][NPI_LISTED]["status"] == "listed"
    assert out["results"]["BASELINE"][NPI_LISTED]["status"] == "original_medicare"
    too_many = {"npis": [f"{i:010d}" for i in range(16)], "plan_keys": ["H0609_083_0"]}
    assert c.post("/api/providers/network", json=too_many).status_code == 422
    elsewhere = c.post("/api/providers/network", json={"npis": [NPI_LISTED], "plan_keys": ["H9999_001_0"]})
    assert elsewhere.status_code == 422 and elsewhere.json()["detail"]["code"] == "unknown_plan"
    assert c.post("/api/providers/network", json={"npis": ["12"], "plan_keys": ["BASELINE"]}).status_code == 422
    off = client(synced)
    start(off)
    off.put("/api/profile", json=_profile())
    lookups_off = off.post("/api/providers/network", json={"npis": [NPI_LISTED], "plan_keys": ["BASELINE"]})
    assert lookups_off.status_code == 503


def test_p10_outbound_requests_carry_no_user_data(
    synced: dict[str, str], mocked: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    c = app(synced)
    start(c)
    prof = sentinel_profile() | {"providers": [{"name": SENTINEL_DOCTOR, "npi": NPI_LISTED, "must_keep": True}]}
    assert c.post("/api/compare", json={"profile": prof}).status_code == 200
    sent = " ".join(f"{call.request.url} {dict(call.request.headers)} {call.request.content!r}"
                    for call in mocked.calls)  # fmt: skip
    assert NPI_LISTED in sent
    for s in (SENTINEL_ZIP, SENTINEL_DRUG, SENTINEL_DOCTOR, "Sentinel", "03060", "Maricopa", "msp_sid"):
        assert s not in sent, s
    assert NPI_LISTED not in caplog.text and SENTINEL_DOCTOR not in caplog.text
