"""End-to-end ingest on the committed fixtures (M1 acceptance), against the compose MySQL as the ingest role."""

from __future__ import annotations

import copy
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, create_engine, event, text

from selector.ingest.run import run_ingest
from selector.ingest.validate import ValidationFailed
from tests.cms_fixtures import FIX, SOURCES_DIR, fixture_fetched

pytestmark = pytest.mark.infra

PLAN_TABLES = ("plan", "plan_county", "pbp_benefit", "pbp_inpatient_interval", "formulary", "plan_formulary",
               "tier_cost", "insulin_cost", "part_d_params")  # fmt: skip


@pytest.fixture
def ingest_engine(scratch_schema: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(scratch_schema["ingest"])
    _forget_markers(eng)  # other tests edit plan tables by hand (e.g. county); start each test from a full load
    yield eng
    eng.dispose()


def _checksums(eng: Engine) -> dict[str, Any]:
    with eng.connect() as c:
        return {r[0]: r[1] for r in c.execute(text("CHECKSUM TABLE " + ",".join([*PLAN_TABLES, "county"])))}


def _ingest(eng: Engine, tmp_path: Path, sources_dir: Path = SOURCES_DIR) -> dict[str, int]:
    return run_ingest(eng, 2027, sources_dir=sources_dir, lock_path=tmp_path / "sources.lock",
                      fetched=fixture_fetched()).counts  # fmt: skip


def _forget_markers(eng: Engine) -> None:
    """Drop the per-table load markers, so the next ingest reloads every table."""
    with eng.begin() as c:
        c.execute(text("DELETE FROM ingest_run WHERE source_id LIKE 'table:%'"))


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
        assert status["03060"] == "crosswalk"
        # AK1 (DESIGN v0.5 B6): Alaska via NBER (XW3), Connecticut via cited overrides, Valdez-Cordova retired.
        assert status["02013"] == "crosswalk_nber" and status["07010"] == "override" and status["02261"] == "retired"
        assert "pending" not in status.values()
        q = "SELECT ssa_code, fips FROM county WHERE state_name IN ('Alaska','Connecticut')"
        fips = dict(c.execute(text(q)).all())
        assert fips["02270"] == "02158" and fips["07010"] == "09003" and fips["02261"] is None


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


def test_failed_validation_takes_the_year_out_of_service(ingest_engine: Engine, tmp_path: Path) -> None:
    """Batched load: a failed validation cannot roll back, so it removes the year's `plan` rows (API not ready for
    that year) and records no `ok` run; other years are untouched."""
    _ingest(ingest_engine, tmp_path)
    with ingest_engine.begin() as c:
        ok_runs = c.execute(text("SELECT COUNT(*) FROM ingest_run WHERE plan_year=2027 AND status='ok'")).scalar()
    spec = yaml.safe_load((SOURCES_DIR / "2027.yaml").read_text())
    bad = copy.deepcopy(spec)
    bad["golden"][0]["moop_in_network_cents"] = 1  # wrong on purpose
    sd = tmp_path / "sources"
    sd.mkdir()
    (sd / "2027.yaml").write_text(yaml.safe_dump(bad))
    (sd / "ssa_fips_overrides.csv").write_text((SOURCES_DIR / "ssa_fips_overrides.csv").read_text())
    with pytest.raises(ValidationFailed, match="moop_in_network_cents"):
        _ingest(ingest_engine, tmp_path, sources_dir=sd)
    with ingest_engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2027")).scalar() == 0
        assert (
            c.execute(text("SELECT COUNT(*) FROM ingest_run WHERE plan_year=2027 AND status='ok'")).scalar() == ok_runs
        )
    _ingest(ingest_engine, tmp_path)  # a good run puts the year back
    with ingest_engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2027")).scalar() == 7


def test_small_batches_load_the_same_rows(
    ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each table loads in transactions of at most BATCH rows (deletes too); the result does not depend on BATCH."""
    from selector.ingest import load

    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    monkeypatch.setattr(load, "BATCH", 3)
    commits: list[int] = []

    def on_commit(conn: object) -> None:
        commits.append(1)

    _forget_markers(ingest_engine)
    event.listen(ingest_engine, "commit", on_commit)
    try:
        counts = _ingest(ingest_engine, tmp_path)
    finally:
        event.remove(ingest_engine, "commit", on_commit)
    assert _checksums(ingest_engine) == before and counts["plan"] == 7
    assert len(commits) > sum(counts.values()) // 3  # many small transactions, not one


def test_plan_rows_go_out_first_and_in_last(
    ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API is ready for a year only when it has `plan` rows, so `plan` is deleted first and inserted last."""
    from selector.ingest import load

    _ingest(ingest_engine, tmp_path)
    calls: list[tuple[str, str]] = []
    real_delete, real_insert = load._delete, load._insert

    def spy_delete(engine: Engine, table: Any, year: int | None) -> None:
        calls.append(("delete", table.name))
        real_delete(engine, table, year)

    def spy_insert(engine: Engine, table: Any, rows: Any, skip: int = 0) -> int:
        calls.append(("insert", table.name))
        return real_insert(engine, table, rows, skip)

    monkeypatch.setattr(load, "_delete", spy_delete)
    monkeypatch.setattr(load, "_insert", spy_insert)
    _forget_markers(ingest_engine)
    _ingest(ingest_engine, tmp_path)
    assert calls[0] == ("delete", "plan") and calls[-1] == ("insert", "plan")
    assert sum(1 for c in calls if c[1] == "plan") == 2


def test_ak4_ingest_fails_when_a_new_pending_county_appears(ingest_engine: Engine, tmp_path: Path) -> None:
    """AK4: with `pending_fips_states: []`, an SSA code no crosswalk or override knows stops the ingest."""
    fixtures = tmp_path / "fix"
    shutil.copytree(FIX, fixtures)
    with (fixtures / "geo.txt").open("a") as f:
        f.write("02999|Alaska|Nowhere Census Area|26|Alaska|34|Alaska\n")
    with pytest.raises(ValidationFailed, match=r"1 counties with a pending SSA→FIPS mapping.*02999"):
        run_ingest(ingest_engine, 2027, sources_dir=SOURCES_DIR, lock_path=tmp_path / "sources.lock",
                   fetched=fixture_fetched(fixtures))  # fmt: skip


def test_ak5_ingest_fails_when_a_plan_still_serves_a_retired_county(ingest_engine: Engine, tmp_path: Path) -> None:
    """AK5 (DESIGN v0.5 B6.1): a PlanArea row naming retired Valdez-Cordova (02261) stops the ingest; never dropped."""
    fixtures = tmp_path / "fix"
    shutil.copytree(FIX, fixtures)
    with (fixtures / "plan_area.txt").open("a") as f:
        f.write("H0028\t028\t0\t1\t01\t01\tH0028_028_0\tH0028\t028\t0\t02261\t0\t\t2027\t0\tValdez-Cordova\tAK\n")
    msg = r"1 plan service-area rows use a retired SSA county.*H0028_028_0.*02261"
    with pytest.raises(ValidationFailed, match=msg):
        run_ingest(ingest_engine, 2027, sources_dir=SOURCES_DIR, lock_path=tmp_path / "sources.lock",
                   fetched=fixture_fetched(fixtures))  # fmt: skip


def test_ak5_region_wide_plans_skip_retired_counties(ingest_engine: Engine, tmp_path: Path) -> None:
    """AK5: a PDP in the Alaska region (34) gets every live Alaska county but not the retired 02261."""
    fixtures = tmp_path / "fix"
    shutil.copytree(FIX, fixtures)
    land = fixtures / "landscape.csv"
    lines = land.read_text().splitlines(keepends=True)
    i = next(n for n, line in enumerate(lines) if ",S4802,134," in line)
    assert lines[i].rstrip("\r\n").endswith(",28,Arizona")
    lines[i] = lines[i].rstrip("\r\n")[: -len(",28,Arizona")] + ",34,Alaska\n"
    land.write_text("".join(lines))
    run_ingest(ingest_engine, 2027, sources_dir=SOURCES_DIR, lock_path=tmp_path / "sources.lock",
               fetched=fixture_fetched(fixtures))  # fmt: skip
    with ingest_engine.connect() as c:
        got = c.execute(text("SELECT ssa_code FROM plan_county WHERE plan_year=2027 AND plan_key='S4802_134_0' "
                             "ORDER BY ssa_code")).scalars().all()  # fmt: skip
    assert got == ["02013", "02063", "02066", "02270"]


def test_api_role_reads_plan_data(ingest_engine: Engine, tmp_path: Path, scratch_schema: dict[str, str]) -> None:
    _ingest(ingest_engine, tmp_path)
    eng = create_engine(scratch_schema["api"])
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2027")).scalar() == 7
    eng.dispose()


class _FlakyLink:
    """The real engine, but one chosen transaction loses its connection: before the work runs (`when="before"`), or
    after it committed so only the reply is lost (`when="after"`)."""

    def __init__(self, engine: Engine, fail_at: int, when: str) -> None:
        self.engine, self.fail_at, self.when, self.n = engine, fail_at, when, 0

    def _lost(self) -> Exception:
        import pymysql  # type: ignore[import-untyped]
        from sqlalchemy.exc import OperationalError

        return OperationalError("INSERT", {}, pymysql.err.OperationalError(2013, "Lost connection (test)"))

    @contextmanager
    def begin(self) -> Iterator[Any]:
        self.n += 1
        if self.n == self.fail_at and self.when == "before":
            raise self._lost()
        with self.engine.begin() as conn:
            yield conn
        if self.n == self.fail_at and self.when == "after":
            raise self._lost()

    def connect(self) -> Any:
        return self.engine.connect()

    def dispose(self) -> None:
        self.engine.dispose()


@pytest.mark.parametrize("when", ["before", "after"])
def test_a_lost_connection_mid_load_is_retried_without_gaps_or_duplicates(
    ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, when: str
) -> None:
    """A batch whose connection drops is retried on a new connection. If it had already committed (reply lost), the
    retry's duplicate key shows that and the load goes on. Either way the result equals a clean load."""
    from selector.ingest import load

    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    monkeypatch.setattr(load, "BATCH", 3)
    monkeypatch.setattr("time.sleep", lambda s: None)
    caplog.set_level("INFO", logger="selector.ingest.load")
    _forget_markers(ingest_engine)
    counting = _FlakyLink(ingest_engine, fail_at=0, when="never")
    run_ingest(counting, 2027, sources_dir=SOURCES_DIR, lock_path=tmp_path / "sources.lock",  # type: ignore[arg-type]
               fetched=fixture_fetched())  # fmt: skip
    fail_at = counting.n - 30  # the last transactions are insert batches (then one for ingest_run)
    caplog.clear()
    _forget_markers(ingest_engine)
    flaky = _FlakyLink(ingest_engine, fail_at=fail_at, when=when)
    run_ingest(flaky, 2027, sources_dir=SOURCES_DIR, lock_path=tmp_path / "sources.lock",  # type: ignore[arg-type]
               fetched=fixture_fetched())  # fmt: skip
    assert flaky.n > fail_at and _checksums(ingest_engine) == before
    logged = caplog.text
    retried = [ln for ln in logged.splitlines() if "reconnecting in 5s (try 2 of 6)" in ln]
    assert len(retried) == 1 and " rows " in retried[0], retried  # an insert batch was retried
    assert ("already committed by the previous try" in logged) == (when == "after")


def _spy_load(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int]]:
    """Record every delete ("delete", table, 0) and insert ("insert", table, rows skipped)."""
    from selector.ingest import load

    calls: list[tuple[str, str, int]] = []
    real_delete, real_insert = load._delete, load._insert

    def spy_delete(engine: Engine, table: Any, year: int | None) -> None:
        calls.append(("delete", table.name, 0))
        real_delete(engine, table, year)

    def spy_insert(engine: Engine, table: Any, rows: Any, skip: int = 0) -> int:
        calls.append(("insert", table.name, skip))
        return real_insert(engine, table, rows, skip)

    monkeypatch.setattr(load, "_delete", spy_delete)
    monkeypatch.setattr(load, "_insert", spy_insert)
    return calls


def test_rerun_with_the_same_data_writes_no_plan_rows(
    ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every table already holds exactly these rows (same fingerprint and count): nothing is deleted or inserted."""
    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    calls = _spy_load(monkeypatch)
    _ingest(ingest_engine, tmp_path)
    assert calls == [] and _checksums(ingest_engine) == before


def test_interrupted_run_continues_where_it_stopped(
    ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that dies inside `tier_cost` (after some batches committed): the re-run skips the finished tables,
    keeps tier_cost's committed rows and inserts only the rest; the result equals a clean load."""
    from selector.ingest import load

    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    _forget_markers(ingest_engine)
    monkeypatch.setattr(load, "BATCH", 100)
    real_insert = load._insert
    batches = {"n": 0}

    def dying_insert(engine: Engine, table: Any, rows: Any, skip: int = 0) -> int:
        if table.name != "tier_cost":
            return real_insert(engine, table, rows, skip)
        rows = list(rows)
        for start in range(skip, len(rows), 100):  # commit two batches, then the process "dies"
            if batches["n"] == 2:
                raise KeyboardInterrupt
            real_insert(engine, table, rows[: start + 100], start)
            batches["n"] += 1
        return len(rows)

    monkeypatch.setattr(load, "_insert", dying_insert)
    with pytest.raises(KeyboardInterrupt):
        _ingest(ingest_engine, tmp_path)
    with ingest_engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM tier_cost WHERE plan_year=2027")).scalar() == 200
        assert c.execute(text("SELECT COUNT(*) FROM plan WHERE plan_year=2027")).scalar() == 0  # not ready

    monkeypatch.setattr(load, "_insert", real_insert)
    calls = _spy_load(monkeypatch)
    _ingest(ingest_engine, tmp_path)
    assert ("insert", "tier_cost", 200) in calls  # continued after the 200 committed rows
    finished = {"county", "plan_county", "pbp_benefit", "pbp_inpatient_interval", "formulary", "plan_formulary"}
    assert not {c[1] for c in calls} & finished, calls  # tables finished before the interruption are kept
    assert ("delete", "tier_cost", 0) not in calls
    assert _checksums(ingest_engine) == before


def test_changed_rows_reload_only_that_table(
    ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New data for one table (different fingerprint) reloads that table, and `plan` (out first, in last)."""
    from selector.ingest import run

    _ingest(ingest_engine, tmp_path)
    real_build = run.build_year

    def build_with_change(*a: Any, **kw: Any) -> Any:
        data = real_build(*a, **kw)
        data.insulin = data.insulin[:-1]  # one row fewer
        return data

    monkeypatch.setattr(run, "build_year", build_with_change)
    calls = _spy_load(monkeypatch)
    _ingest(ingest_engine, tmp_path)
    assert calls == [("delete", "plan", 0), ("delete", "insulin_cost", 0), ("insert", "insulin_cost", 0),
                     ("insert", "plan", 0)]  # fmt: skip


def test_full_reloads_every_table(ingest_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`selector ingest --full` ignores the markers: every table is deleted and loaded again."""
    _ingest(ingest_engine, tmp_path)
    before = _checksums(ingest_engine)
    calls = _spy_load(monkeypatch)
    run_ingest(ingest_engine, 2027, sources_dir=SOURCES_DIR, lock_path=tmp_path / "sources.lock",
               fetched=fixture_fetched(), full=True)  # fmt: skip
    deleted = {c[1] for c in calls if c[0] == "delete"}
    assert deleted >= {"county", "plan", "formulary", "tier_cost"} and _checksums(ingest_engine) == before


def test_ingest_role_can_kill_its_own_stuck_session(scratch_schema: dict[str, str]) -> None:
    """The KILL that closes a dropped connection's server session works for the plain ingest user (no admin right),
    and ingest sessions get the short server-side idle limits."""
    from selector.db import ingest_engine_for
    from selector.ingest import load

    eng = ingest_engine_for(scratch_schema["ingest"])
    try:
        stuck = eng.connect()
        tid = load._server_thread_id(stuck)
        assert tid is not None
        with eng.connect() as c:
            assert c.execute(text("SELECT @@session.wait_timeout, @@session.net_read_timeout")).one() == (600, 120)
        load._kill_server_session(eng, tid)
        with eng.connect() as c:
            alive = c.execute(text("SELECT COUNT(*) FROM information_schema.processlist WHERE id=:i"), {"i": tid})
            assert alive.scalar() == 0
        stuck.invalidate()
    finally:
        eng.dispose()
