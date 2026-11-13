"""End-to-end ingest on the committed fixtures (M1 acceptance), against the compose MySQL as the ingest role."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, create_engine, text

from selector.ingest.run import run_ingest
from selector.ingest.validate import ValidationFailed
from tests.cms_fixtures import SOURCES_DIR, fixture_fetched

pytestmark = pytest.mark.infra

PLAN_TABLES = ("plan", "plan_county", "pbp_benefit", "pbp_inpatient_interval", "formulary", "plan_formulary",
               "tier_cost", "insulin_cost", "part_d_params")  # fmt: skip


@pytest.fixture
def ingest_engine(scratch_schema: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(scratch_schema["ingest"])
    yield eng
    eng.dispose()


def _checksums(eng: Engine) -> dict[str, Any]:
    with eng.connect() as c:
        return {r[0]: r[1] for r in c.execute(text("CHECKSUM TABLE " + ",".join([*PLAN_TABLES, "county"])))}


def _ingest(eng: Engine, tmp_path: Path, sources_dir: Path = SOURCES_DIR) -> dict[str, int]:
    return run_ingest(eng, 2027, sources_dir=sources_dir, lock_path=tmp_path / "sources.lock",
                      fetched=fixture_fetched()).counts  # fmt: skip


def test_golden_row_and_counts(ingest_engine: Engine, tmp_path: Path) -> None:
    counts = _ingest(ingest_engine, tmp_path)
    assert counts["plan"] == 7
    with ingest_engine.connect() as c:
        g = c.execute(text(
            "SELECT part_c_premium_cents, part_d_deductible_cents, moop_in_network_cents, star_overall "
            "FROM plan WHERE plan_year=2027 AND plan_key='H0028_028_0'")).one()  # fmt: skip
        assert (g[0], g[1], g[2], str(g[3])) == (0, 32500, 655000, "4.5")
        assert c.execute(text("SELECT oop_threshold_cents FROM part_d_params WHERE plan_year=2027")).scalar() == 240000
        fips = c.execute(text(
            "SELECT c.fips FROM plan_county pc JOIN county c USING(ssa_code) "
            "WHERE pc.plan_year=2027 AND pc.plan_key='H0028_028_0' ORDER BY c.fips")).scalars().all()  # fmt: skip
        assert fips == ["04013", "04015", "04025"]
        # Regional PPO and PDPs get their whole region (15 Arizona counties).
        for key in ("R7220_001_0", "S4802_092_0"):
            n = c.execute(text("SELECT COUNT(*) FROM plan_county WHERE plan_year=2027 AND plan_key=:k"), {"k": key})
            assert n.scalar() == 15, key
        status = dict(c.execute(text("SELECT ssa_code, fips_status FROM county")).all())
        assert status["02013"] == "pending" and status["03060"] == "crosswalk"


def test_rerun_makes_no_changes(ingest_engine: Engine, tmp_path: Path) -> None:
    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    _ingest(ingest_engine, tmp_path)
    assert _checksums(ingest_engine) == before


def test_other_years_untouched(ingest_engine: Engine, tmp_path: Path) -> None:
    with ingest_engine.begin() as c:
        c.execute(text("DELETE FROM plan WHERE plan_year=2026"))
        c.execute(text(
            "INSERT INTO plan (plan_year, plan_key, contract_id, plan_id, segment_id, category, plan_type, "
            "org_marketing_name, plan_name, sanctioned, part_d_suppressed, src_ref) VALUES "
            "(2026, 'H0028_028_0', 'H0028', '028', '0', 'MAPD', 'HMO', 'x', 'x', 0, 0, '{}')"))  # fmt: skip
    _ingest(ingest_engine, tmp_path)
    with ingest_engine.begin() as c:
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2026")).scalar() == 1
        c.execute(text("DELETE FROM plan WHERE plan_year=2026"))


def test_failed_validation_rolls_back(ingest_engine: Engine, tmp_path: Path) -> None:
    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    spec = yaml.safe_load((SOURCES_DIR / "2027.yaml").read_text())
    bad = copy.deepcopy(spec)
    bad["golden"][0]["moop_in_network_cents"] = 1  # wrong on purpose
    sd = tmp_path / "sources"
    sd.mkdir()
    (sd / "2027.yaml").write_text(yaml.safe_dump(bad))
    (sd / "ssa_fips_overrides.csv").write_text((SOURCES_DIR / "ssa_fips_overrides.csv").read_text())
    with pytest.raises(ValidationFailed, match="moop_in_network_cents"):
        _ingest(ingest_engine, tmp_path, sources_dir=sd)
    assert _checksums(ingest_engine) == before


def test_api_role_reads_plan_data(ingest_engine: Engine, tmp_path: Path, scratch_schema: dict[str, str]) -> None:
    _ingest(ingest_engine, tmp_path)
    eng = create_engine(scratch_schema["api"])
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2027")).scalar() == 7
    eng.dispose()
