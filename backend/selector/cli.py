"""`selector` command line: migrations, ingest, maintenance jobs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

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

    url = get_settings().effective_migrator_url
    schema = make_url(url).database or "msp"
    with make_engine(url).begin() as conn:
        n = apply_grants(conn, schema, args.ingest_user, args.api_user)
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
    from selector.db import make_engine
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
    try:
        res = run_ingest(
            make_engine(get_settings().effective_ingest_url),
            args.year,
            accept_new=args.accept_new,
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


def cmd_hud_preload(args: argparse.Namespace) -> int:
    from selector.db import make_engine
    from selector.geo.hud import HudClient, store_zip_counties

    s = get_settings()
    client = HudClient(s.hud_api_token.get_secret_value(), s.hud_api_base)
    rows = client.state_counties(args.state)
    with make_engine(s.effective_ingest_url).begin() as conn:
        n = store_zip_counties(conn, rows)
    print(f"cached {n} ZIP-county rows for {args.state}")
    return 0


def cmd_hud_load_file(args: argparse.Namespace) -> int:
    from selector.db import make_engine
    from selector.geo.hud import store_zip_counties
    from selector.geo.hud_file import HudFileError, read_hud_file

    try:
        rows = read_hud_file(Path(args.path), args.year, args.quarter)
    except (HudFileError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.state:
        from selector.geo.hud_file import state_filter

        rows = state_filter(rows, args.state)
    total = 0
    with make_engine(get_settings().effective_ingest_url).begin() as conn:
        for i in range(0, len(rows), 2000):
            total += store_zip_counties(conn, rows[i : i + 2000])
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
    g.add_argument("--ingest-user", default="msp_ingest")
    g.add_argument("--api-user", default="msp_api")
    g.set_defaults(func=cmd_db_grants)

    i = sub.add_parser("ingest", help="fetch, validate and load one plan year of CMS data")
    i.add_argument("--year", type=int, required=True)
    i.add_argument("--accept-new", action="store_true", help="accept sources that differ from sources.lock")
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
