"""`selector` command line: migrations, ingest, maintenance jobs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selector.geo.hud import ZipCounty

from selector.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(url: str) -> object:
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def cmd_migrate(args: argparse.Namespace) -> int:
    from alembic import command

    cfg = _alembic_config(get_settings().effective_migrator_url)
    if args.direction == "up":
        command.upgrade(cfg, args.revision or "head")  # type: ignore[arg-type]
    else:
        command.downgrade(cfg, args.revision or "base")  # type: ignore[arg-type]
    return 0


def cmd_db_grants(args: argparse.Namespace) -> int:
    from sqlalchemy.engine import make_url

    from selector.db import make_engine
    from selector.grants import apply_grants

    s = get_settings()
    url = s.effective_migrator_url
    schema = make_url(url).database or "msp"
    # Users default to the ones named in INGEST_DATABASE_URL / DATABASE_URL (the dev defaults when those are unset).
    ingest_user = args.ingest_user or (make_url(s.ingest_database_url).username if s.ingest_database_url else None)
    ingest_user = ingest_user or "msp_ingest"
    api_user = args.api_user or make_url(s.database_url).username or "msp_api"
    # Any user works for any role. A role that uses the migrator's own user needs no grants (it has every right);
    # separate ingest/API users get table-level rights, the API user read-only on plan tables (DESIGN §4).
    migrator_user = make_url(url).username
    ingest = None if ingest_user == migrator_user else ingest_user
    api = None if api_user == migrator_user else api_user
    if ingest is None and api is None:
        print(f"db-grants: ingest and API use the migrator user ({migrator_user}); no grants needed")
        return 0
    from sqlalchemy.exc import DBAPIError

    try:
        with make_engine(url).begin() as conn:
            n = apply_grants(conn, schema, ingest, api)
    except DBAPIError as e:
        # 1044/1142/1410: the migrator may not grant (e.g. a DO panel user without GRANT OPTION). The users then
        # keep the rights the database admin gave them; migrate and ingest still work.
        if getattr(e.orig, "args", [None])[0] not in (1044, 1142, 1410):
            raise
        print(f"db-grants: WARNING: {migrator_user} may not grant rights ({e.orig}); skipped", file=sys.stderr)
        return 0
    print(f"applied {n} grants on {schema}")
    return 0


def cmd_ephemeral_flush(args: argparse.Namespace) -> int:
    import redis

    from selector.store.ephemeral_store import flush_all_ephemeral

    n = flush_all_ephemeral(redis.Redis.from_url(get_settings().redis_url))
    print(f"flushed {n} ephemeral keys")
    return 0


EXIT_NO_DATA = 3


def cmd_check_data(args: argparse.Namespace) -> int:
    """Print a loud, actionable error when the API would not be ready (run by the container entrypoint)."""
    import redis

    from selector import readiness
    from selector.db import make_engine

    s = get_settings()
    eng = make_engine(s.database_url)
    try:
        rc = None if args.data_only else redis.Redis.from_url(s.redis_url, socket_connect_timeout=5)
        r = readiness.check(eng, rc, s.plan_year)
    finally:
        eng.dispose()
    if r.ok:
        print(f"plan data for {s.plan_year}: ready")
        return 0
    bar = "!" * 78
    print(f"{bar}\nNOT READY ({r.reason}, plan year {s.plan_year}):\n{r.hint}\n{bar}", file=sys.stderr)
    # 3 = only the plan data is missing (`make app-up` then loads the dev sample data); 1 = anything else.
    return EXIT_NO_DATA if r.reason in ("schema_missing", "no_plan_data") else 1


def cmd_purge(args: argparse.Namespace) -> int:
    """Nightly retention purge (DESIGN §8.1): idle Saved sessions and old feedback."""
    from selector.db import make_engine
    from selector.store.mysql_store import purge_expired

    s = get_settings()
    with make_engine(s.database_url).begin() as conn:
        out = purge_expired(conn, s.retention_days, s.feedback_retention_days)
    print(f"purged {out['sessions']} sessions, {out['feedback']} feedback rows")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    import logging

    from selector.db import ingest_engine_for
    from selector.ingest.manifest import LockMismatch
    from selector.ingest.run import run_ingest
    from selector.ingest.validate import ValidationFailed

    kwargs: dict[str, object] = {}
    if args.fixtures is not None:
        import tempfile

        from selector.ingest.devdata import FIXTURE_ROOT, fixture_fetched

        root = Path(args.fixtures) if args.fixtures else FIXTURE_ROOT / str(args.year)
        kwargs["fetched"] = fixture_fetched(root)
        # Fixture runs never touch the real sources.lock.
        kwargs["lock_path"] = Path(tempfile.mkdtemp(prefix="msp-devlock-")) / "sources.lock"
    # Progress and reconnect messages from selector.ingest (a real load can take a while over a long link).
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        res = run_ingest(
            ingest_engine_for(get_settings().effective_ingest_url),
            args.year,
            accept_new=args.accept_new,
            full=args.full,
            offline=args.offline,
            **kwargs,  # type: ignore[arg-type]
        )
    except (LockMismatch, ValidationFailed) as e:
        print(str(e), file=sys.stderr)
        return 2
    for table, n in sorted(res.counts.items()):
        print(f"{table:>24} {n:>10}")
    if res.lock_changed and args.fixtures is None:
        print("sources.lock updated — review and commit it")
    return 0


def _store_zip_rows(rows: Sequence[ZipCounty]) -> int:
    """Upsert ZIP→county rows 1,000 per transaction, reconnecting on a stuck link like `selector ingest` (an upsert
    can be sent again safely)."""
    from sqlalchemy import Connection

    from selector.db import ingest_engine_for
    from selector.geo.hud import store_zip_counties
    from selector.ingest.load import _in_transaction

    engine = ingest_engine_for(get_settings().effective_ingest_url)
    total = 0
    for i in range(0, len(rows), 1000):
        chunk = list(rows[i : i + 1000])

        def work(conn: Connection, chunk: list[ZipCounty] = chunk) -> int:
            return store_zip_counties(conn, chunk)

        total += _in_transaction(engine, f"zip_county_cache rows {i + 1:,}-{i + len(chunk):,} of {len(rows):,}", work)
    engine.dispose()
    return total


def cmd_hud_preload(args: argparse.Namespace) -> int:
    from selector.geo.hud import HudClient

    s = get_settings()
    token = s.hud_api_token.get_secret_value()
    if not token:
        print("HUD_API_TOKEN is not set (docs/design/HUD-API-SETUP.md); or load a HUD file: "
              "make zip-data HUD_FILE=ZIP_COUNTY_<MMYYYY>.xlsx", file=sys.stderr)  # fmt: skip
        return 2
    rows = HudClient(token, s.hud_api_base).state_counties(args.state)
    n = _store_zip_rows(rows)
    print(f"cached {n} ZIP-county rows for {args.state}")
    return 0


def cmd_hud_load_file(args: argparse.Namespace) -> int:
    from selector.geo.hud_file import HudFileError, read_hud_file

    try:
        rows = read_hud_file(Path(args.path), args.year, args.quarter)
    except (HudFileError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.state:
        from selector.geo.hud_file import state_filter

        rows = state_filter(rows, args.state)
    total = _store_zip_rows(rows)
    print(f"cached {total} ZIP-county rows from {Path(args.path).name}")
    return 0


def cmd_directories_sync(args: argparse.Namespace) -> int:
    """Seed directory_endpoint from sources/directories.yaml and refresh insurance_plan_map (addendum A3.5)."""
    from selector.db import make_engine
    from selector.directories import seed_endpoints, sync_endpoint
    from selector.network import SOURCES_FILE, load_sources

    endpoints, _, spec = load_sources(Path(args.sources) if args.sources else SOURCES_FILE)
    notes = {str(e["id"]): str(e.get("notes") or "") for e in spec.get("endpoints", [])}
    eng = make_engine(get_settings().effective_ingest_url)
    with eng.begin() as conn:
        n = seed_endpoints(conn, endpoints, notes, str(spec["verified_at"]))
    print(f"directory_endpoint: {n} endpoints")
    if args.seed_only:
        return 0
    failed = 0
    for ep in endpoints:
        if args.carrier and ep.id != args.carrier:
            continue
        r = sync_endpoint(eng, args.year, ep, max_pages=args.max_pages, min_interval_s=args.interval)
        failed += r.error is not None and ep.usable
        print(f"{ep.id}: {r.seen} InsurancePlans read, {r.mapped} matched to {args.year} plans"
              + (f" ({r.error})" if r.error else ""))  # fmt: skip
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="selector")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("migrate", help="run Alembic migrations")
    m.add_argument("direction", choices=["up", "down"])
    m.add_argument("revision", nargs="?")
    m.set_defaults(func=cmd_migrate)

    g = sub.add_parser("db-grants", help="apply table-level grants for the ingest and API roles")
    g.add_argument("--ingest-user", default=None, help="default: user in INGEST_DATABASE_URL, else msp_ingest")
    g.add_argument("--api-user", default=None, help="default: user in DATABASE_URL")
    g.set_defaults(func=cmd_db_grants)

    i = sub.add_parser("ingest", help="fetch, validate and load one plan year of CMS data")
    i.add_argument("--year", type=int, required=True)
    i.add_argument("--accept-new", action="store_true", help="accept sources that differ from sources.lock")
    i.add_argument(
        "--full", action="store_true", help="reload every table, even ones already loaded with the same rows"
    )
    i.add_argument("--offline", action="store_true", help="reuse files already in data/raw/<year>")
    i.add_argument(
        "--fixtures",
        nargs="?",
        const="",
        default=None,
        metavar="DIR",
        help="load the committed CMS sample fixtures (dev only; default backend/tests/fixtures/cms/<year>)",
    )
    i.set_defaults(func=cmd_ingest)

    h = sub.add_parser("hud", help="HUD ZIP→county crosswalk")
    hsub = h.add_subparsers(dest="hud_cmd", required=True)
    hp = hsub.add_parser("preload", help="bulk-load zip_county_cache for a state (or All)")
    hp.add_argument("--state", required=True, help="2-letter state code or All")
    hp.set_defaults(func=cmd_hud_preload)
    hf = hsub.add_parser("load-file", help="fallback without a token: load a HUD ZIP_COUNTY .xlsx/.csv file")
    hf.add_argument("path")
    hf.add_argument("--year", type=int)
    hf.add_argument("--quarter", type=int, choices=[1, 2, 3, 4])
    hf.add_argument("--state", help="only keep ZIPs whose county FIPS is in this 2-letter state")
    hf.set_defaults(func=cmd_hud_load_file)

    dr = sub.add_parser("directories", help="public provider directories (Plan-Net FHIR) for doctor checks")
    drsub = dr.add_subparsers(dest="dir_cmd", required=True)
    ds = drsub.add_parser("sync", help="load sources/directories.yaml and map carriers' InsurancePlans to plans")
    ds.add_argument("--year", type=int, required=True)
    ds.add_argument("--carrier", help="only this endpoint id (e.g. uhc, humana)")
    ds.add_argument("--max-pages", type=int, default=200, help="InsurancePlan pages per carrier (100 per page)")
    ds.add_argument("--interval", type=float, default=1.0, help="seconds between requests to one host")
    ds.add_argument("--seed-only", action="store_true", help="only load the endpoint list (no network)")
    ds.add_argument("--sources", help="another directories.yaml (tests)")
    ds.set_defaults(func=cmd_directories_sync)

    f = sub.add_parser("ephemeral-flush", help="delete all No-save (eph:*) keys; run at API start")
    f.set_defaults(func=cmd_ephemeral_flush)

    cd = sub.add_parser(
        "check-data", help="fix-it message; exit 3 if the plan data is missing, 1 if MySQL/Redis are not reachable"
    )
    cd.add_argument("--data-only", action="store_true", help="skip the Redis check (used by `make dev-data`)")
    cd.set_defaults(func=cmd_check_data)

    pg = sub.add_parser(
        "purge", help="delete Saved sessions idle > RETENTION_DAYS and feedback > FEEDBACK_RETENTION_DAYS"
    )
    pg.set_defaults(func=cmd_purge)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
