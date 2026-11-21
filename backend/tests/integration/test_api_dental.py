"""WP12 on the committed CMS fixtures: plan_dental loaded by the ingest, GET /api/plans/{plan_key}/benefits, the
Dental column in POST /api/compare and the `get_plan_benefits` tool."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from selector.agent.providers import ToolCall
from selector.agent.tools import ToolContext, execute
from selector.profile import Profile
from tests.api_support import client, settings, start

pytestmark = pytest.mark.infra


def test_ingest_loads_dental_for_every_ma_fixture_plan(fixture_db: dict[str, str]) -> None:
    eng = create_engine(fixture_db["api"])
    with eng.connect() as c:
        keys = set(c.execute(text("SELECT plan_key FROM plan_dental WHERE plan_year=2027")).scalars())
        ma = set(c.execute(text("SELECT plan_key FROM plan WHERE plan_year=2027 AND category<>'PDP'")).scalars())
    eng.dispose()
    assert keys == ma  # extra b16 sample rows (not in the Landscape sample) are filtered out


def test_benefits_endpoint(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    assert c.get("/api/plans/H0028_028_0/benefits").status_code == 401  # needs a session
    start(c)
    r = c.get("/api/plans/H0028_028_0/benefits?category=dental")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plan_key"] == "H0028_028_0" and d["category"] == "dental" and d["plan_year"] == 2027
    assert d["dental"]["preventive_max_cents"] == 50_000 and d["dental"]["max_shared"] is True
    assert any(s["code"] == "prm" and s["coins_max_pct"] == 50.0 for s in d["dental"]["services"])
    assert {"source": "S2", "vintage": "2027-pbp-20261001", "row": "b16:H0028_028_0"} in d["src_ref"]
    pdp = c.get("/api/plans/S4802_092_0/benefits").json()
    assert pdp["dental"]["summary"] == "No routine dental"
    assert c.get("/api/plans/H9999_999_0/benefits").json()["detail"]["code"] == "unknown_plan"
    assert c.get("/api/plans/not-a-plan/benefits").status_code == 422
    assert c.get("/api/plans/H0028_028_0/benefits?category=vision").status_code == 422


def test_compare_rows_carry_dental_and_must_have(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    start(c)
    prof = {"county_ssa": "03060", "county_name": "Maricopa", "state": "AZ"}
    rows = {r["plan_key"]: r for r in c.post("/api/compare", json={"profile": prof}).json()["canvas"]["rows"]}
    assert rows["H0028_028_0"]["dental"]["summary"] == "Preventive $0 · Comprehensive 0–50% · Max $500/yr (shared)"
    assert rows["S4802_092_0"]["dental"]["summary"] == "No routine dental"
    prof["must_haves"] = {"dental": True}
    out = c.post("/api/compare", json={"profile": prof}).json()["canvas"]
    by = {r["plan_key"]: r for r in out["rows"]}
    assert by["H0028_028_0"]["rank"] is not None
    assert by["S4802_092_0"]["dropped_reason"] == "No preventive dental benefit (you asked for dental)."
    assert out["baseline"]["rank"] is None and out["baseline"]["dropped_reason"] is None


def test_get_plan_benefits_tool(fixture_db: dict[str, str]) -> None:
    eng = create_engine(fixture_db["api"])
    ctx = ToolContext(eng, settings(fixture_db), Profile())
    out = execute(ctx, ToolCall("t1", "get_plan_benefits", {"plan_key": "H0028_028_0"}))
    assert out["dental"]["yearly_max_cents"] == 50_000 and out["src_ref"]
    bad = execute(ctx, ToolCall("t2", "get_plan_benefits", {"plan_key": "H0028_028_0", "category": "vision"}))
    assert bad["error"] == "bad_arguments"
    eng.dispose()
