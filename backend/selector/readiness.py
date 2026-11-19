"""Readiness: can the API actually answer? (QA #6)

`/api/health` is liveness only (the process runs). Readiness also checks that Redis answers and that the plan
tables exist and hold data for `PLAN_YEAR`. On the dev stack MySQL runs on tmpfs, so recreating the container
silently drops the schema, grants and data; readiness turns that into a loud, actionable failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Engine, literal, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from selector.models import plan

log = logging.getLogger("selector.readiness")

HINT_DATA = (
    "The plan database is empty or missing. Load data, then restart the API: `make ingest-dev` (dev sample data; "
    "needed again after the dev MySQL container is recreated, because it runs on tmpfs) or `make ingest` (real "
    "CMS data). Then `make app-up`."
)
HINT_DB = "MySQL is not reachable. Start it with `make stack-up` and check DATABASE_URL."
HINT_REDIS = "Redis is not reachable. Start it with `make stack-up` and check REDIS_URL."

# MySQL errors that mean "the schema or its grants are not there": 1044 access denied to database,
# 1049 unknown database, 1142 table command denied, 1146 table doesn't exist.
_SCHEMA_ERRORS = {1044, 1049, 1142, 1146}


@dataclass(frozen=True)
class Readiness:
    ok: bool
    reason: str = "ready"
    hint: str = ""

    def as_json(self) -> dict[str, str]:
        if self.ok:
            return {"status": "ready"}
        return {"status": "not_ready", "reason": self.reason, "hint": self.hint}


def _mysql_code(e: DBAPIError) -> int | None:
    args = getattr(e.orig, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def check(engine: Engine, redis_client: object, plan_year: int) -> Readiness:
    try:
        redis_client.ping()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - any Redis failure means not ready
        return Readiness(False, "redis_unavailable", HINT_REDIS)
    try:
        with engine.connect() as conn:
            found = conn.execute(select(literal(1)).select_from(plan).where(plan.c.plan_year == plan_year).limit(1))
            has_data = found.first() is not None
    except DBAPIError as e:
        if _mysql_code(e) in _SCHEMA_ERRORS:
            return Readiness(False, "schema_missing", HINT_DATA)
        return Readiness(False, "db_unavailable", HINT_DB)
    except SQLAlchemyError:
        return Readiness(False, "db_unavailable", HINT_DB)
    if not has_data:
        return Readiness(False, "no_plan_data", HINT_DATA)
    return Readiness(True)


def log_not_ready(r: Readiness, plan_year: int) -> None:
    log.error("NOT READY (%s, plan year %d): %s", r.reason, plan_year, r.hint)
