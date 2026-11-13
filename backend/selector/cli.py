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


def cmd_ingest(args: argparse.Namespace) -> int:
    from selector.db import make_engine
    from selector.ingest.manifest import LockMismatch
    from selector.ingest.run import run_ingest
    from selector.ingest.validate import ValidationFailed

    try:
        res = run_ingest(
            make_engine(get_settings().effective_ingest_url),
            args.year,
            accept_new=args.accept_new,
            offline=args.offline,
        )
    except (LockMismatch, ValidationFailed) as e:
        print(str(e), file=sys.stderr)
        return 2
    for table, n in sorted(res.counts.items()):
        print(f"{table:>24} {n:>10}")
    if res.lock_changed:
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
    i.set_defaults(func=cmd_ingest)

    h = sub.add_parser("hud", help="HUD ZIP→county crosswalk")
    hsub = h.add_subparsers(dest="hud_cmd", required=True)
    hp = hsub.add_parser("preload", help="bulk-load zip_county_cache for a state (or All)")
    hp.add_argument("--state", required=True, help="2-letter state code or All")
    hp.set_defaults(func=cmd_hud_preload)

    f = sub.add_parser("ephemeral-flush", help="delete all No-save (eph:*) keys; run at API start")
    f.set_defaults(func=cmd_ephemeral_flush)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
