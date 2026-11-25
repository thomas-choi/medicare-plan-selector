"""Build all plan-data rows for one `plan_year` and load them (DESIGN §4).

The load is delete-and-insert for that year, so other years are untouched. `county` holds geography for all years
and is replaced as a whole. Each table is loaded in its own transactions of at most BATCH rows, so a slow or
long-distance connection (e.g. to DO Managed MySQL) never carries one huge transaction. The year's `plan` rows are
deleted first and inserted last: the API is ready for a year only when it has `plan` rows (selector.readiness), so
a half-finished load is never served.

A re-run does only the work that is left. Each table has a marker row in `ingest_run` (`source_id` "table:<name>",
status `loading`/`loaded`, `sha256` = fingerprint of the rows it should hold). A table whose marker is `loaded` with
the same fingerprint and row count is skipped; one whose marker is `loading` with the same fingerprint continues
after the rows already committed (batches commit in order, so those are always the first rows). Anything else is
deleted and reloaded. New CMS files, crosswalks or parser changes change the fingerprint, so stale rows are never
kept.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, Table, delete, func, insert, select
from sqlalchemy.exc import DBAPIError

from selector import models as m
from selector.config import get_settings
from selector.ingest.fetch import Fetched
from selector.ingest.manifest import sha256_bytes
from selector.ingest.normalize import src_ref
from selector.ingest.parsers import county_xwalk, decode, landscape, pbp, pbp_dental, read_delimited, spuf

BATCH = 1_000  # rows per transaction (inserts and deletes); small, so a stalled send loses little
# MySQL client/server errors that mean "this connection is gone or stuck": retry the batch on a new connection.
# 2006 server gone (PyMySQL also raises it for a write timeout), 2013 lost connection (read timeout), 2055 lost
# connection at handshake, 1205 lock wait timeout (the server still holds the dropped connection's batch).
RETRYABLE = frozenset({2006, 2013, 2055, 1205})
DUPLICATE_KEY = 1062
RETRY_WAIT_S = (5, 10, 20, 30, 30)
log = logging.getLogger(__name__)
YEAR_TABLES: Sequence[Table] = (
    m.plan,
    m.plan_county,
    m.pbp_benefit,
    m.pbp_inpatient_interval,
    m.formulary,
    m.plan_formulary,
    m.tier_cost,
    m.insulin_cost,
    m.part_d_params,
    m.medicare_params,
    m.plan_dental,
)


@dataclass
class YearData:
    year: int
    plans: list[dict[str, Any]] = field(default_factory=list)
    counties: list[dict[str, Any]] = field(default_factory=list)
    plan_county: list[dict[str, Any]] = field(default_factory=list)
    pbp_benefit: list[dict[str, Any]] = field(default_factory=list)
    inpatient: list[dict[str, Any]] = field(default_factory=list)
    formulary: list[dict[str, Any]] = field(default_factory=list)
    plan_formulary: list[dict[str, Any]] = field(default_factory=list)
    tier_cost: list[dict[str, Any]] = field(default_factory=list)
    insulin: list[dict[str, Any]] = field(default_factory=list)
    part_d_params: dict[str, Any] = field(default_factory=dict)
    medicare_params: dict[str, Any] = field(default_factory=dict)
    dental: list[dict[str, Any]] = field(default_factory=list)
    oop_thresholds: set[int] = field(default_factory=set)

    def rows_for(self, table: Table) -> list[dict[str, Any]]:
        return {
            "plan": self.plans,
            "plan_county": self.plan_county,
            "pbp_benefit": self.pbp_benefit,
            "pbp_inpatient_interval": self.inpatient,
            "formulary": self.formulary,
            "plan_formulary": self.plan_formulary,
            "tier_cost": self.tier_cost,
            "insulin_cost": self.insulin,
            "part_d_params": [self.part_d_params] if self.part_d_params else [],
            "medicare_params": [self.medicare_params] if self.medicare_params else [],
            "plan_dental": self.dental,
        }[table.name]


def _read(p: Path) -> str:
    return decode(p.read_bytes())


def build_year(year: int, fetched: dict[str, Fetched], spec: dict[str, Any], overrides_csv: Path) -> YearData:
    d = YearData(year)
    s1, s2, s3, xw1 = fetched["S1"], fetched["S2"], fetched["S3"], fetched["XW1"]

    # Plans (S1). Landscape is the authoritative plan list; other files are filtered to it.
    landscape_text = _read(s1.paths["landscape"])
    state_abbr: dict[str, str] = {}
    for r in read_delimited(landscape_text, ",", landscape.EXPECTED_HEADER):
        state_abbr.setdefault(r["State Territory Name"].strip(), r["State Territory Abbreviation"].strip())
    for p in landscape.parse(landscape_text, s1.entry.vintage):
        oop = p.pop("_oop_threshold_cents")
        if oop is not None:
            d.oop_thresholds.add(oop)
        d.plans.append({"plan_year": year, **p})
    plan_keys = {p["plan_key"] for p in d.plans}

    # Counties (S3 geo locator + SSA→FIPS crosswalks XW1, XW3 + cited overrides; DESIGN v0.5 B6).
    xwalk = county_xwalk.parse_penetration(_read(xw1.paths["penetration"]))
    nber = county_xwalk.parse_nber(_read(fetched["XW3"].paths["file"])) if "XW3" in fetched else {}
    overrides = county_xwalk.parse_overrides(overrides_csv.read_text())
    geo = list(spuf.parse_geo(_read(s3.paths["geo"])))
    counties = list(county_xwalk.build_counties(geo, xwalk, overrides, s3.entry.vintage, nber))
    per_fips: dict[str, int] = defaultdict(int)
    for c in counties:
        c["state"] = state_abbr.get(c["state_name"])
        if c["fips"]:
            per_fips[c["fips"]] += 1
    for c in counties:
        if c["fips"] and per_fips[c["fips"]] > 1:
            c["partial"] = True  # several SSA rating codes share this county
    d.counties = counties

    # Service area: MA from PBP PlanArea; PDP from its PDP region.
    pc: set[tuple[str, str]] = set()
    for r in pbp.parse_plan_area(_read(s2.paths["plan_area"])):
        if r["plan_key"] in plan_keys:
            pc.add((r["plan_key"], r["ssa_code"]))
    # Region-wide plans (PDPs, Regional PPOs) skip `retired` SSA areas (DESIGN v0.5 B6.1): the S3 locator still lists
    # them in their region, but they are no longer real places. A PlanArea row naming one fails validation instead.
    live = [c for c in counties if c["fips_status"] != "retired"]
    by_region: dict[str, list[str]] = defaultdict(list)
    for c in live:
        if c["pdp_region_code"]:
            by_region[c["pdp_region_code"]].append(c["ssa_code"])
    by_ma_region: dict[str, list[str]] = defaultdict(list)
    for c in live:
        if c["ma_region_code"]:
            by_ma_region[c["ma_region_code"]].append(c["ssa_code"])
    in_plan_area = {k for k, _ in pc}
    for p in d.plans:
        if p["category"] == "PDP" and p["pdp_region_code"]:
            for ssa in by_region.get(p["pdp_region_code"], []):
                pc.add((p["plan_key"], ssa))
        elif p["plan_key"] not in in_plan_area and p["plan_type"].startswith("Regional PPO") and p["ma_region_code"]:
            # Regional PPOs are not in PBP PlanArea; they serve their whole MA region (Landscape MA Region Code).
            for ssa in by_ma_region.get(p["ma_region_code"], []):
                pc.add((p["plan_key"], ssa))
    d.plan_county = [{"plan_year": year, "plan_key": k, "ssa_code": s} for k, s in sorted(pc)]

    # Medical benefits (S2).
    for section in ("b7", "b4", "b9"):
        for r in pbp.parse_section(_read(s2.paths[section]), section, s2.entry.vintage):
            if r["plan_key"] in plan_keys:
                d.pbp_benefit.append({"plan_year": year, **r})
    for kind, r in pbp.parse_inpatient(_read(s2.paths["b1a"]), s2.entry.vintage):
        if r["plan_key"] not in plan_keys:
            continue
        (d.inpatient if kind == "interval" else d.pbp_benefit).append({"plan_year": year, **r})
    # Dental (S2 b16, addendum A4).
    for r in pbp_dental.parse_dental(_read(s2.paths["b16"]), s2.entry.vintage):
        if r["plan_key"] in plan_keys:
            d.dental.append({"plan_year": year, **r})

    # Part D (S3).
    pf: dict[str, str] = {}
    suppressed: set[str] = set()
    for r in spuf.parse_plan_info(_read(s3.paths["plan_info"])):
        if r["plan_key"] not in plan_keys:
            continue
        if r["suppressed"]:
            suppressed.add(r["plan_key"])
        else:
            pf.setdefault(r["plan_key"], r["formulary_id"])
    for p in d.plans:
        p["part_d_suppressed"] = p["plan_key"] in suppressed and p["plan_key"] not in pf
    d.plan_formulary = [{"plan_year": year, "plan_key": k, "formulary_id": f} for k, f in sorted(pf.items())]
    used = set(pf.values())
    d.formulary = [
        {"plan_year": year, **r}
        for r in spuf.parse_formulary(_read(s3.paths["formulary"]), s3.entry.vintage)
        if r["formulary_id"] in used
    ]
    d.tier_cost = [
        {"plan_year": year, **r}
        for r in spuf.parse_beneficiary_cost(_read(s3.paths["cost"]), s3.entry.vintage)
        if r["plan_key"] in plan_keys
    ]
    d.insulin = [
        {"plan_year": year, **r}
        for r in spuf.parse_insulin(_read(s3.paths["insulin"]), s3.entry.vintage)
        if r["plan_key"] in plan_keys
    ]

    params = spec["params"]["part_d"]
    d.part_d_params = {
        "plan_year": year,
        "std_deductible_cents": int(params["std_deductible_cents"]),
        "oop_threshold_cents": int(params["oop_threshold_cents"]),
        "src_ref": src_ref("S6", str(params["vintage"]), "part_d_params", url=params["citation"]),
    }
    d.medicare_params = medicare_params_row(year, spec)
    return d


MEDICARE_FIELDS = (
    "part_b_premium_cents", "part_b_deductible_cents", "part_b_coins_pct", "part_a_deductible_cents",
    "part_a_day61_cents", "part_a_lifetime_cents", "snf_day21_cents", "medigap_hd_deductible_cents",
    "medigap_n_office_copay_cents", "medigap_n_er_copay_cents",
)  # fmt: skip
MEDICARE_GROUPS = ("part_b", "part_a", "medigap_hd", "medigap_n")


def medicare_params_row(year: int, spec: dict[str, Any]) -> dict[str, Any]:
    """The `medicare_params` row from `params.medicare` in sources/<year>.yaml; every group must be cited."""
    mp = spec["params"]["medicare"]
    cites = mp.get("citations") or {}
    missing = [g for g in MEDICARE_GROUPS if not (cites.get(g) or {}).get("url")]
    if missing:
        raise ValueError(f"sources/{year}.yaml params.medicare: no citation for {missing}")
    refs = {
        g: src_ref(str(cites[g]["source"]), str(cites[g]["vintage"]), f"medicare_params:{g}", url=cites[g]["url"])
        for g in MEDICARE_GROUPS
    }
    return {"plan_year": year, **{f: int(mp[f]) for f in MEDICARE_FIELDS}, "src_ref": refs}


def _mysql_code(e: DBAPIError) -> int | None:
    args = getattr(e.orig, "args", None)
    return args[0] if args and isinstance(args[0], int) else None


def _server_thread_id(conn: Connection) -> int | None:
    """The server's id for this connection (PyMySQL gets it at connect; no query)."""
    try:
        return int(conn.connection.dbapi_connection.thread_id())  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - not a PyMySQL connection (tests) or already closed
        return None


def _kill_server_session(engine: Engine, thread_id: int) -> None:
    """End the server side of a connection we dropped (MySQL lets a user KILL its own sessions). It frees the
    session and any row locks of its unfinished batch. Best effort: the session may already be gone."""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(f"KILL {int(thread_id)}")
        log.info("closed the stuck server session %d", thread_id)
    except DBAPIError as e:
        log.info("server session %d already gone (%s)", thread_id, e.orig)


def _in_transaction(engine: Engine, what: str, work: Callable[[Connection], Any], *, insert_batch: bool = False) -> Any:
    """Run `work` in its own transaction. A dropped or stuck connection is closed on both sides (our socket, then
    KILL of its server session from the new connection), and the work is retried on a new connection
    (`INGEST_BATCH_ATTEMPTS` tries in all). Safe because each batch is one transaction: it committed in full or not
    at all. For an insert, a duplicate key on a retry means the earlier try did commit (only the reply was lost), so
    the batch counts as done."""
    attempts = max(1, get_settings().ingest_batch_attempts)
    stale: int | None = None  # server session of the connection that just failed
    for attempt in range(1, attempts + 1):
        if stale is not None:
            _kill_server_session(engine, stale)
            stale = None
        thread_id: int | None = None
        try:
            with engine.begin() as conn:
                thread_id = _server_thread_id(conn)
                return work(conn)
        except DBAPIError as e:
            code = _mysql_code(e)
            if insert_batch and attempt > 1 and code == DUPLICATE_KEY:
                log.warning("%s: already committed by the previous try; continuing", what)
                return None
            if code not in RETRYABLE and not e.connection_invalidated:
                raise
            if attempt == attempts:
                log.error("%s: connection failed %d times; giving up", what, attempts)
                raise
            wait = RETRY_WAIT_S[min(attempt, len(RETRY_WAIT_S)) - 1]
            log.warning("%s: connection lost or stuck (%s); reconnecting in %ds (try %d of %d)",
                        what, e.orig, wait, attempt + 1, attempts)  # fmt: skip
            engine.dispose()  # drop every pooled connection; the next try opens a new one
            stale = thread_id
            time.sleep(wait)
    raise AssertionError("unreachable")


def _delete(engine: Engine, table: Table, year: int | None) -> None:
    """Delete this year's rows (all rows when `year` is None), at most BATCH per transaction."""
    stmt = delete(table) if year is None else delete(table).where(table.c.plan_year == year)
    stmt = stmt.with_dialect_options(mysql_limit=BATCH)
    while _in_transaction(engine, f"delete {table.name}", lambda c: c.execute(stmt).rowcount) >= BATCH:
        pass


def _insert(engine: Engine, table: Table, rows: Iterable[dict[str, Any]], skip: int = 0) -> int:
    """Insert `rows` after the first `skip`, at most BATCH per transaction, each batch retried on a new connection if
    the link drops."""
    rows = list(rows)
    total = len(rows)
    for start in range(skip, total, BATCH):
        batch = rows[start : start + BATCH]
        end = start + len(batch)

        def work(conn: Connection, batch: list[dict[str, Any]] = batch) -> None:
            conn.execute(insert(table), batch)

        _in_transaction(engine, f"{table.name} rows {start + 1:,}-{end:,} of {total:,}", work, insert_batch=True)
        if end == total or end % 100_000 == 0:
            log.info("%s: %s of %s rows", table.name, f"{end:,}", f"{total:,}")
    return total


MARKER = "table:"  # ingest_run.source_id prefix of the per-table load markers
SHARED_YEAR = 0  # marker year for `county`, which every plan year shares


def fingerprint(rows: Sequence[dict[str, Any]]) -> str:
    """sha256 of the rows a table should hold, in load order."""
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True, default=str, separators=(",", ":")).encode())
        h.update(b"\n")
    return h.hexdigest()


def _marker(engine: Engine, year: int, name: str) -> tuple[str, str] | None:
    ir = m.ingest_run
    with engine.connect() as conn:
        row = conn.execute(
            select(ir.c.status, ir.c.sha256)
            .where(ir.c.plan_year == year, ir.c.source_id == MARKER + name)
            .order_by(ir.c.id.desc())
            .limit(1)
        ).first()
    return (row[0], row[1]) if row else None


def _set_marker(engine: Engine, year: int, name: str, status: str | None, sha: str = "", n: int = 0) -> None:
    """Replace the table's marker (`status=None` removes it)."""
    ir = m.ingest_run

    def work(conn: Connection) -> None:
        conn.execute(delete(ir).where(ir.c.plan_year == year, ir.c.source_id == MARKER + name))
        if status:
            now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
            conn.execute(insert(ir).values(plan_year=year, source_id=MARKER + name, url="", vintage="", sha256=sha,
                                           row_count=n, status=status, started_at=now, finished_at=now))  # fmt: skip

    _in_transaction(engine, f"marker {name}", work)


def _count(engine: Engine, table: Table, year: int | None) -> int:
    q = select(func.count()).select_from(table)
    if year is not None:
        q = q.where(table.c.plan_year == year)
    with engine.connect() as conn:
        return int(conn.execute(q).scalar_one())


@dataclass
class _Plan:
    table: Table
    year: int | None  # None: the table is not per year (county)
    rows: list[dict[str, Any]]
    sha: str
    skip: int | None  # None: delete and reload; n: keep the first n rows (n == len(rows): nothing to do)

    @property
    def marker_year(self) -> int:
        return SHARED_YEAR if self.year is None else self.year

    @property
    def done(self) -> bool:
        return self.skip == len(self.rows)


def _plan_table(engine: Engine, table: Table, year: int | None, rows: list[dict[str, Any]], mark_year: int) -> _Plan:
    sha = fingerprint(rows)
    mk = _marker(engine, mark_year, table.name)
    skip: int | None = None
    if mk and mk[1] == sha:
        have = _count(engine, table, year)
        if mk[0] == "loaded" and have == len(rows) or mk[0] == "loading" and have <= len(rows):
            skip = have
    return _Plan(table, year, rows, sha, skip)


def _load(engine: Engine, p: _Plan) -> None:
    name, total = p.table.name, len(p.rows)
    if p.done and p.skip is not None and _marker(engine, p.marker_year, name) == ("loaded", p.sha):
        log.info("%s: %s rows unchanged, skipped", name, f"{total:,}")
        return
    if p.skip is None:
        # Order matters for a crash at any step: no marker → full reload; `loading` → rows are a clean prefix.
        _set_marker(engine, p.marker_year, name, None)
        _delete(engine, p.table, p.year)
        _set_marker(engine, p.marker_year, name, "loading", p.sha)
    elif p.skip:
        log.info("%s: continuing after %s of %s rows loaded earlier", name, f"{p.skip:,}", f"{total:,}")
    _insert(engine, p.table, p.rows, skip=p.skip or 0)
    _set_marker(engine, p.marker_year, name, "loaded", p.sha, total)


def forget_markers(engine: Engine, year: int) -> None:
    """Forget what is loaded for `year` (and `county`), so the next load reloads every table."""
    ir = m.ingest_run
    _in_transaction(engine, "forget markers", lambda c: c.execute(
        delete(ir).where(ir.c.plan_year.in_((year, SHARED_YEAR)), ir.c.source_id.startswith(MARKER))))  # fmt: skip


def load_year(engine: Engine, data: YearData, *, full: bool = False) -> dict[str, int]:
    """Load this year's plan data (and the county table): only the tables that are not already loaded with the same
    rows, one batch per transaction.

    When any table needs work, `plan` goes first out and last in, so the year is not ready (no `plan` rows) while the
    other tables load. `full=True` reloads every table (e.g. after plan tables were edited by hand)."""
    if full:
        forget_markers(engine, data.year)
    others = [_plan_table(engine, m.county, None, list(data.counties), SHARED_YEAR)]
    others += [_plan_table(engine, t, data.year, data.rows_for(t), data.year) for t in YEAR_TABLES if t is not m.plan]
    plan = _plan_table(engine, m.plan, data.year, data.rows_for(m.plan), data.year)
    if not all(p.done for p in others):
        _set_marker(engine, data.year, "plan", None)  # out first, back in last
        _delete(engine, m.plan, data.year)
        plan.skip = 0  # now empty: insert everything, no second delete
    for p in others:
        _load(engine, p)
    _load(engine, plan)
    return {p.table.name: len(p.rows) for p in [*others, plan]}


def unpublish_year(engine: Engine, year: int) -> None:
    """Take a year out of service after a failed validation: without `plan` rows the API is not ready for it."""
    _set_marker(engine, year, "plan", None)
    _delete(engine, m.plan, year)


def record_runs(conn: Connection, year: int, fetched: dict[str, Fetched], counts: dict[str, int], status: str) -> None:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    for sid, f in fetched.items():
        conn.execute(
            insert(m.ingest_run).values(
                plan_year=year,
                source_id=sid,
                url=f.entry.url,
                vintage=f.entry.vintage,
                # Range-read sources have no whole-file hash: store the hash of the sorted member hashes.
                sha256=f.entry.sha256 or sha256_bytes("".join(sorted(f.entry.members.values())).encode()),
                row_count=sum(counts.values()),
                status=status,
                started_at=now,
                finished_at=now,
            )
        )
