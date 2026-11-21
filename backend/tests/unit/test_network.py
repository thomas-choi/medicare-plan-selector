"""WP13 (addendum A3): directory listing checks on recorded-shape Plan-Net bundles (UHC relative references, Humana
absolute references, as seen on 2026-11-19), the opt-out list, budgets and what leaves the server."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

import httpx
import pytest
import respx

from selector.cost.engine import CostProfile, MustHaves, compare, doctor_fit
from selector.cost.params import Weights
from selector.network import (
    NETWORK_EXT,
    NPI_SYSTEM,
    DirectoryChecker,
    DoctorRef,
    Endpoint,
    Listing,
    OptOutConfig,
    PlanDirectory,
    load_sources,
    map_insurance_plan,
    status_text,
)
from tests.unit.cost.factories import PARAMS, medical, plan_info, plan_rx

UHC = Endpoint("uhc", "UnitedHealthcare", "https://uhc.example/R4", org_patterns=("UnitedHealthcare",),
               plan_id_system="urn:cms:medicare-advantage-contract",
               plan_id_format=r"^(?P<contract>[HR]\d{4})(?P<plan>\d{3})(?P<segment>\d{3})$")  # fmt: skip
HUM_FORMAT = r"^(?P<contract>[HR]\d{4})-(?P<plan>\d{3})-(?P<segment>\d{3})-(?P<year>\d{4})$"
HUM = Endpoint(
    "humana",
    "Humana",
    "https://hum.example/api",
    org_patterns=("Humana",),
    plan_id_system="https://fhir.humana.com/documentation/glossary/PlanId",
    plan_id_format=HUM_FORMAT,
)
OPTOUT = OptOutConfig("https://data.cms.example/data-api/v1/dataset/x/data", "Opt Out 2026-09-01")
TODAY = dt.date(2026, 11, 19)
NPI_A, NPI_B, NPI_C = "1437170412", "1679052898", "1111111112"


def bundle(*resources: dict[str, Any], next_url: str | None = None) -> dict[str, Any]:
    links = [{"relation": "self", "url": "x"}] + ([{"relation": "next", "url": next_url}] if next_url else [])
    return {"resourceType": "Bundle", "type": "searchset", "link": links,
            "entry": [{"resource": r} for r in resources]}  # fmt: skip


def prac(pid: str, npi: str) -> dict[str, Any]:
    return {"resourceType": "Practitioner", "id": pid, "identifier": [{"system": NPI_SYSTEM, "value": npi}]}


def role(rid: str, prac_ref: str, *nets: str) -> dict[str, Any]:
    ext = [{"url": NETWORK_EXT, "valueReference": {"reference": n}} for n in nets]
    return {"resourceType": "PractitionerRole", "id": rid, "practitioner": {"reference": prac_ref}, "extension": ext}


def checker(**kw: Any) -> DirectoryChecker:
    return DirectoryChecker(OPTOUT, http=httpx.Client(), min_interval_s=0, today=lambda: TODAY, **kw)


PLANS = [
    PlanDirectory("H0609_083_0", "MAPD", "uhc", frozenset({"Organization/netA", "Organization/netA2"}), True),
    PlanDirectory("H0609_099_0", "MAPD", "uhc", frozenset({"Organization/netZ"}), True),
    PlanDirectory("H0028_028_0", "MAPD", "humana", frozenset({"Organization/hum1"}), True),
    PlanDirectory("H0028_077_0", "MAPD", "humana", frozenset(), False),  # carrier directory, plan not matched
    PlanDirectory("H9999_001_0", "MAPD", None),  # no public directory known
    PlanDirectory("H8888_001_0", "MAPD", "aetna"),
    PlanDirectory("S4802_092_0", "PDP", None),
    PlanDirectory("BASELINE", "BASELINE", None),
]
ENDPOINTS = {"uhc": UHC, "humana": HUM, "aetna": Endpoint("aetna", "Aetna", "https://aetna.example", auth="app_key")}


def _mock(r: respx.MockRouter) -> None:
    r.get("https://uhc.example/R4/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_A}"}).respond(
        json=bundle(prac("pA", NPI_A))
    )
    r.get("https://uhc.example/R4/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_B}"}).respond(json=bundle())
    r.get("https://uhc.example/R4/PractitionerRole").respond(
        json=bundle(role("r1", "Practitioner/pA", "Organization/netA", "Organization/other"))
    )
    r.get("https://hum.example/api/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_A}"}).respond(
        json=bundle(prac("hA", NPI_A))
    )
    r.get("https://hum.example/api/Practitioner", params={"identifier": f"{NPI_SYSTEM}|{NPI_B}"}).respond(
        json=bundle(prac("hB", NPI_B))
    )
    r.get("https://hum.example/api/PractitionerRole", params={"practitioner": "Practitioner/hA"}).respond(
        json=bundle(role("x", "https://hum.example/api/Practitioner/hA", "https://hum.example/api/Organization/hum1"))
    )
    r.get("https://hum.example/api/PractitionerRole", params={"practitioner": "Practitioner/hB"}).respond(
        json=bundle(role("y", "https://hum.example/api/Practitioner/hB", "https://hum.example/api/Organization/hX"))
    )
    r.get(OPTOUT.url, params={"filter[NPI]": NPI_A}).respond(json=[])
    r.get(OPTOUT.url, params={"filter[NPI]": NPI_B}).respond(json=[{"NPI": NPI_B, "Optout Effective Date": "2016-10-01",
                                                                  "Optout End Date": "2028-10-01"}])  # fmt: skip


def test_p6_listed_not_listed_unknown_unavailable_mapping() -> None:
    docs = [DoctorRef("Ana Test", NPI_A, True), DoctorRef("Bo Test", NPI_B, True)]
    with respx.mock(assert_all_called=False) as r:
        _mock(r)
        out = checker().check(docs, PLANS, ENDPOINTS)
    st = {k: {n: v.status for n, v in d.items()} for k, d in out.items()}
    assert st["H0609_083_0"] == {NPI_A: "listed", NPI_B: "not_listed"}  # B: no Practitioner at UHC (supported)
    assert st["H0609_099_0"] == {NPI_A: "not_listed", NPI_B: "not_listed"}
    assert st["H0028_028_0"] == {NPI_A: "listed", NPI_B: "not_listed"}  # Humana absolute refs normalized
    assert st["H0028_077_0"] == {NPI_A: "unknown", NPI_B: "unknown"}
    assert st["H9999_001_0"] == {NPI_A: "unavailable", NPI_B: "unavailable"}
    assert st["H8888_001_0"] == {NPI_A: "unavailable", NPI_B: "unavailable"}  # needs an app key: never called
    assert out["H0609_083_0"][NPI_A].checked_at == TODAY


def test_p9_original_medicare_rows_use_the_opt_out_list() -> None:
    docs = [DoctorRef("Ana Test", NPI_A), DoctorRef("Bo Test", NPI_B)]
    with respx.mock(assert_all_called=False) as r:
        _mock(r)
        out = checker().check(docs, PLANS, ENDPOINTS)
    for k in ("S4802_092_0", "BASELINE"):
        assert out[k][NPI_A].status == "original_medicare" and out[k][NPI_B].status == "opted_out"
    assert status_text("opted_out", TODAY) == "Opted out of Medicare: you'd pay this doctor yourself."
    assert out["BASELINE"][NPI_A].source["source"] == "S14"


def test_p6_unreachable_is_unavailable_within_budget() -> None:
    docs = [DoctorRef("Ana Test", NPI_A, True)]
    with respx.mock(assert_all_called=False) as r:
        r.get("https://uhc.example/R4/Practitioner").mock(side_effect=httpx.ConnectTimeout("down"))
        r.get(OPTOUT.url).mock(side_effect=httpx.ConnectTimeout("down"))
        out = checker().check(docs, PLANS[:1] + PLANS[-1:], ENDPOINTS)
    assert out["H0609_083_0"][NPI_A].status == "unavailable" and out["BASELINE"][NPI_A].status == "unavailable"

    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(1.0)
        return httpx.Response(200, json=bundle())

    with respx.mock(assert_all_called=False) as r:
        r.get("https://uhc.example/R4/Practitioner").mock(side_effect=slow)
        t0 = time.monotonic()
        out = checker(budget_s=0.2).check(docs, PLANS[:1], ENDPOINTS)
        assert time.monotonic() - t0 < 0.9
    assert out["H0609_083_0"][NPI_A].status == "unavailable"


def test_p6_truncated_role_pages_give_unknown_not_not_listed() -> None:
    docs = [DoctorRef("Ana Test", NPI_A)]
    many = frozenset({f"Organization/n{i}" for i in range(60)})  # > MAX_FILTER_REFS: no network= filter
    plan = PlanDirectory("H0609_083_0", "MAPD", "uhc", many, True)
    with respx.mock(assert_all_called=False) as r:
        r.get("https://uhc.example/R4/Practitioner").respond(json=bundle(prac("pA", NPI_A)))
        r.get("https://uhc.example/R4/PractitionerRole").respond(
            json=bundle(role("r", "Practitioner/pA", "Organization/zzz"), next_url="https://uhc.example/R4?page=2")
        )
        r.get("https://uhc.example/R4").respond(
            json=bundle(role("r", "Practitioner/pA", "Organization/zzz"), next_url="https://uhc.example/R4?page=3")
        )
        out = checker().check(docs, [plan], ENDPOINTS)
    assert out["H0609_083_0"][NPI_A].status == "unknown"


def test_p10_only_npis_and_directory_ids_leave_the_server() -> None:
    docs = [DoctorRef("Ana Test", NPI_A, True), DoctorRef("Bo Test", NPI_B)]
    with respx.mock(assert_all_called=False) as r:
        _mock(r)
        checker().check(docs, PLANS, ENDPOINTS)
        sent = [str(c.request.url) for c in r.calls] + [str(dict(c.request.headers)) for c in r.calls]
    assert sent
    blob = " ".join(sent)
    for forbidden in ("Ana", "Test", "85004", "03060", "metformin", "H0609", "H0028", "session", "cookie"):
        assert forbidden not in blob, forbidden
    assert all(NPI_A in u or NPI_B in u or "PractitionerRole" in u for u in sent[: len(sent) // 2])


def test_no_npi_doctors_send_nothing() -> None:
    with respx.mock(assert_all_called=False) as r:
        out = checker().check([DoctorRef("Dr Typed", None)], PLANS, ENDPOINTS)
        assert not r.calls
    assert all(v == {} for v in out.values())


def test_insurance_plan_mapping_uhc_and_humana() -> None:
    uhc = {"resourceType": "InsurancePlan", "id": "abc",
           "identifier": [{"system": "urn:cms:medicare-advantage-contract", "value": "H2406076000"}],
           "network": [{"reference": "Organization/n1"}, {"reference": "Organization/n2"}]}  # fmt: skip
    assert map_insurance_plan(UHC, uhc) == ("H2406_076_0", "abc", ["Organization/n1", "Organization/n2"])
    hum = {"resourceType": "InsurancePlan", "id": "h",
           "identifier": [{"system": "https://fhir.humana.com/documentation/glossary/PlanId",
                           "value": "H3642-001-000-2027"}],
           "network": [{"reference": "https://hum.example/api/Organization/z9"}]}  # fmt: skip
    assert map_insurance_plan(HUM, hum) == ("H3642_001_0", "h", ["Organization/z9"])
    assert map_insurance_plan(UHC, {"resourceType": "InsurancePlan", "id": "x"}) is None  # commercial, no CMS id


def test_seed_file_and_settings_agree() -> None:
    from selector.config import Settings

    eps, oo, spec = load_sources()
    assert {e.id for e in eps} >= {"uhc", "humana", "aetna"}
    assert all(e.base_url.startswith("https://") for e in eps)
    assert next(e for e in eps if e.id == "aetna").auth == "app_key"
    assert "key" not in str(spec).lower().replace("app_key", "")  # public URLs only, never keys
    s = Settings(_env_file=None)
    assert oo is not None and s.optout_url == oo.url and s.optout_vintage == oo.vintage


# ---------------------------------------------------------------- engine: filter and weight (P7)


def _doc(status: str, must_keep: bool = True, name: str = "Ana Test") -> dict[str, Any]:
    return Listing(status, TODAY).as_dict(DoctorRef(name, NPI_A, must_keep))


def test_p7_filter_drops_only_not_listed_must_keep() -> None:
    plans = [plan_info(k, org=k) for k in ("H0001_001_0", "H0002_001_0", "H0003_001_0", "H0004_001_0")]
    rx = {p.plan_key: plan_rx({"1": 1}, key=p.plan_key) for p in plans}
    med = {p.plan_key: medical(p.plan_key) for p in plans}
    doctors = {
        "H0001_001_0": [_doc("listed")],
        "H0002_001_0": [_doc("not_listed")],
        "H0003_001_0": [_doc("unknown"), _doc("unavailable")],
        "H0004_001_0": [_doc("not_listed", must_keep=False)],
    }
    on = CostProfile(must_haves=MustHaves(doctors_listed=True))
    by = {e.plan.plan_key: e for e in compare(plans, rx, med, on, PARAMS, None, doctors)}
    reason = by["H0002_001_0"].dropped_reason
    assert reason == "Your doctor Ana Test isn't in this plan's directory (checked Nov 19)."
    assert all(by[k].rank is not None for k in ("H0001_001_0", "H0003_001_0", "H0004_001_0"))
    off = {e.plan.plan_key: e for e in compare(plans, rx, med, CostProfile(), PARAMS, None, doctors)}
    assert all(e.rank is not None for e in off.values())  # default: badges only
    assert off["H0002_001_0"].as_dict()["doctors"][0]["text"].startswith("Not found in the plan's directory")


def test_p7_doctor_fit_weight_is_off_by_default_and_counts_unknown_half() -> None:
    assert doctor_fit([_doc("listed"), _doc("unknown")]) == 0.75
    assert doctor_fit([_doc("not_listed", must_keep=False)]) == 1.0
    plans = [plan_info("H0001_001_0", org="A", premium_d=0), plan_info("H0002_001_0", org="B", premium_d=900)]
    rx = {p.plan_key: plan_rx({"1": 1}, key=p.plan_key) for p in plans}
    med = {p.plan_key: medical(p.plan_key) for p in plans}
    doctors = {"H0001_001_0": [_doc("not_listed")], "H0002_001_0": [_doc("listed")]}
    base = [e.plan.plan_key for e in compare(plans, rx, med, CostProfile(), PARAMS) if e.rank]
    same = [e.plan.plan_key for e in compare(plans, rx, med, CostProfile(), PARAMS, None, doctors) if e.rank]
    assert base == same == ["H0001_001_0", "H0002_001_0"]
    heavy = CostProfile(weights=Weights(total_cost=0.1, worst_case=0, stars=0, must_have_fit=0, doctor_fit=1.0))
    assert [e.plan.plan_key for e in compare(plans, rx, med, heavy, PARAMS, None, doctors) if e.rank][0] == (
        "H0002_001_0"
    )


@pytest.mark.parametrize("status", ["listed", "not_listed", "unknown", "unavailable", "original_medicare",
                                    "opted_out", "no_npi"])  # fmt: skip
def test_every_status_has_ui_text(status: str) -> None:
    assert status_text(status, TODAY)
