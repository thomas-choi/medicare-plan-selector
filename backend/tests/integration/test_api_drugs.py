"""GET /api/drugs end to end (Thomas's 2026-11-19 report): the full "tamsulosin 0.4 mg capsule" string returns
RxCUI 863669 with `matched_as`, an empty result says so, and an RxNav outage is a 503 the UI can show."""

from __future__ import annotations

import httpx
import pytest
import respx

from selector.lookups import RxNavClient
from tests.api_support import client, start
from tests.unit.test_drug_search import BASE, FX, TAMSULOSIN_CAPSULE, mock_drugs

pytestmark = pytest.mark.infra


@respx.mock
def test_drug_search_endpoint(fixture_db: dict[str, str]) -> None:
    respx.route(host="testserver").pass_through()
    c = client(fixture_db)
    c.app.state.msp.rxnav = RxNavClient(httpx.Client(), min_interval_s=0)  # type: ignore[attr-defined]
    start(c)
    mock_drugs({"tamsulosin": "drugs_tamsulosin"})
    respx.get(f"{BASE}/approximateTerm.json").mock(return_value=httpx.Response(200, json={"approximateGroup": {}}))

    full = c.get("/api/drugs", params={"q": "tamsulosin 0.4 mg capsule"}).json()
    assert full["candidates"][0]["rxcui"] == TAMSULOSIN_CAPSULE
    assert full["matched_as"] == "tamsulosin" and full["how"] == "ingredient"

    part = c.get("/api/drugs", params={"q": "tamsulosin"}).json()
    assert part["how"] == "exact" and TAMSULOSIN_CAPSULE in [d["rxcui"] for d in part["candidates"]]

    none = c.get("/api/drugs", params={"q": "zzqx"}).json()
    assert none == {"candidates": [], "matched_as": None, "how": "none"}

    assert c.get("/api/drugs", params={"q": "t"}).status_code == 422
    assert FX  # fixtures shared with the unit tests


@respx.mock
def test_drug_search_outage_is_503(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    c.app.state.msp.rxnav = RxNavClient(httpx.Client(), min_interval_s=0)  # type: ignore[attr-defined]
    start(c)
    respx.get(f"{BASE}/drugs.json").mock(side_effect=httpx.ConnectError("no route to host"))
    r = c.get("/api/drugs", params={"q": "tamsulosin"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "lookup_failed"
