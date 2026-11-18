"""Golden cost JSON on the committed CMS fixtures (Maricopa, AZ), through the DB loaders and the engine."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine

from selector.config import Settings
from selector.cost import repo
from selector.cost.engine import CostProfile, compare
from selector.cost.part_d import DrugInput

pytestmark = pytest.mark.infra
GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "cost_maricopa_2027.json"
DRUGS = (DrugInput("metformin (fixture RxCUI)", rxcui="197361"), DrugInput("brand (fixture RxCUI)", rxcui="285018"))


@pytest.fixture
def api(fixture_db: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(fixture_db["api"])
    yield eng
    eng.dispose()


def _run(api: Engine, ssa: str, profile: CostProfile) -> list[dict[str, Any]]:
    with api.connect() as c:
        params = repo.load_params(c, 2027, Settings())
        plans = repo.plans_in_county(c, 2027, ssa)
        rx = repo.load_plan_rx(c, 2027, plans, list(profile.drugs))
        med = repo.load_plan_medical(c, 2027, plans)
    return [e.as_dict() for e in compare(plans, rx, med, profile, params)]


def _summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "plan_key",
        "rank",
        "dropped_reason",
        "total_low_cents",
        "total_high_cents",
        "worst_case_cents",
        "drug_low_cents",
        "drug_high_cents",
        "medical_low_cents",
        "medical_high_cents",
        "drugs_covered",
    )
    return [{k: r[k] for k in keys} for r in rows]


def test_golden_maricopa(api: Engine) -> None:
    rows = _summary(_run(api, "03060", CostProfile(drugs=DRUGS, utilization="medium")))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(rows, indent=2) + "\n")
    assert rows == json.loads(GOLDEN.read_text())


def test_h0028_028_0_by_hand(api: Engine) -> None:
    """Hand check of the golden plan: $0 premiums, Part B placeholder, tier-1 $0 generic, tier-3 17% brand with
    an unknown price ($100/month low band) after the $325 deductible, medium utilization copays."""
    rows = {r["plan_key"]: r for r in _run(api, "03060", CostProfile(drugs=DRUGS, utilization="medium"))}
    g = rows["H0028_028_0"]
    part_b = 20_290 * 12
    drug_low = 3 * 10_000 + (2_500 + 1_275) + 8 * 1_700
    medical_low = 4 * 3_500 + 5_000 + 13_000
    assert g["drug_low_cents"] == drug_low == 47_375
    assert g["medical_low_cents"] == medical_low
    assert g["total_low_cents"] == part_b + drug_low + medical_low
    assert g["worst_case_cents"] == part_b + g["drug_high_cents"] + 655_000
    assert g["moop_cents"] == 655_000 and g["part_d_deductible_cents"] == 32_500 and g["star_overall"] == 4.5
    assert g["drugs_covered"] == 2 and g["rank"] is not None


def test_multi_county_zip_plans_differ(api: Engine) -> None:
    """Multi-county ZIP 85142 (Maricopa/Pinal): the plan list depends on the county the user picks."""
    with api.connect() as c:
        maricopa = {p.plan_key for p in repo.plans_in_county(c, 2027, "03060")}
        pinal = {p.plan_key for p in repo.plans_in_county(c, 2027, "03100")}
    assert "H0028_028_0" in maricopa and "H0028_028_0" not in pinal
    assert {"S4802_092_0", "R7220_001_0"} <= maricopa & pinal


def test_zero_drugs_and_snp_hidden(api: Engine) -> None:
    rows = _run(api, "03060", CostProfile())
    ranked = [r["plan_key"] for r in rows if r["rank"]]
    assert "H0028_077_0" not in ranked  # C-SNP hidden unless eligible
    assert all(r["drug_low_cents"] == 0 for r in rows)
