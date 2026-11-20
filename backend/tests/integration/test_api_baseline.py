"""WP11 on the committed CMS fixtures (Maricopa, AZ): the pinned baseline in POST /api/compare (B1, B4, B6)."""

from __future__ import annotations

from typing import Any

import pytest

from selector.cost.medical import original_allowed_b_cents
from tests.api_support import client, start

pytestmark = pytest.mark.infra

DRUGS = [{"name": "metformin (fixture RxCUI)", "rxcui": "197361"}, {"name": "brand (fixture RxCUI)", "rxcui": "285018"}]
PDPS = {"S4802_092_0", "S4802_134_0"}  # the fixture PDPs offered in Maricopa


def _profile(**kw: Any) -> dict[str, Any]:
    return {"county_ssa": "03060", "county_name": "Maricopa", "state": "AZ", "drugs": DRUGS, **kw}


def _compare(db: dict[str, str], **kw: Any) -> dict[str, Any]:
    c = client(db)
    start(c)
    r = c.post("/api/compare", json={"profile": _profile(**kw)})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


@pytest.mark.parametrize("path", ["ma", "original", "both"])
def test_b1_baseline_pinned_on_every_path(fixture_db: dict[str, str], path: str) -> None:
    canvas = _compare(fixture_db, path=path)["canvas"]
    b = canvas["baseline"]
    assert b["plan_key"] == "BASELINE" and b["pinned"] is True and b["rank"] is None
    assert b["pdp_plan_key"] in PDPS
    assert all(r["plan_key"] != "BASELINE" for r in canvas["rows"])
    assert all(r["delta_vs_baseline_cents"] == r["total_est_cents"] - b["total_est_cents"] for r in canvas["rows"])


def test_b4_golden_maricopa_baseline(fixture_db: dict[str, str]) -> None:
    out = _compare(fixture_db, utilization="medium")
    b = out["canvas"]["baseline"]
    allowed = original_allowed_b_cents("medium")
    assert b["medical_low_cents"] == 29_200 + round((allowed - 29_200) * 0.2)
    assert b["worst_case_cents"] is None and b["moop_cents"] is None
    assert b["part_b_annual_cents"] == 20_940 * 12 and b["part_a_deductible_cents"] == 177_600
    # The baseline's PDP is the cheaper of the two fixture PDPs by premium × 12 + drug midpoint.
    rows = {r["plan_key"]: r for r in out["canvas"]["rows"]}

    def cost(k: str) -> int:
        r = rows[k]
        return int(r["premium_annual_cents"] + (r["drug_low_cents"] + r["drug_high_cents"]) // 2)

    assert b["pdp_plan_key"] == min(sorted(PDPS), key=cost)
    pdp = rows[b["pdp_plan_key"]]
    assert b["drug_low_cents"] == pdp["drug_low_cents"] and b["drug_high_cents"] == pdp["drug_high_cents"]
    assert (
        b["total_low_cents"]
        == pdp["premium_annual_cents"] + 20_940 * 12 + pdp["drug_low_cents"] + b["medical_low_cents"]
    )


def test_b6_medigap_quote_round_trip(fixture_db: dict[str, str]) -> None:
    b = _compare(fixture_db, medigap={"plan": "G", "monthly_premium_cents": 14_500})["canvas"]["baseline"]
    assert b["medigap"] == {"plan": "G", "premium_included": True, "rule_note": b["medigap"]["rule_note"]}
    assert b["medical_low_cents"] == 29_200 and b["worst_case_cents"] is not None
    nq = _compare(fixture_db, medigap={"plan": "HDG"})["canvas"]["baseline"]
    assert nq["medigap"]["premium_included"] is False
    assert any("Medigap premium not included" in n for n in nq["notes"])
