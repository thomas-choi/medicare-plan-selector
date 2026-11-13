"""Table-level grants for the ingest and API roles (DESIGN §4: the API user is read-only on plan data)."""

from __future__ import annotations

from sqlalchemy import Connection, text

from selector.models import NOSAVE_ALLOWED_TABLES, PLAN_TABLES, USER_TABLES

RW = "SELECT, INSERT, UPDATE, DELETE"


def grant_statements(schema: str, ingest_user: str, api_user: str) -> list[str]:
    stmts: list[str] = []
    for t in PLAN_TABLES:
        stmts.append(f"GRANT {RW} ON `{schema}`.`{t}` TO '{ingest_user}'@'%'")
        stmts.append(f"GRANT SELECT ON `{schema}`.`{t}` TO '{api_user}'@'%'")
    # Runtime ZIP→county cache fill on a miss (saved mode only; No-save never writes it).
    stmts.append(f"GRANT INSERT, UPDATE ON `{schema}`.`zip_county_cache` TO '{api_user}'@'%'")
    for t in sorted(USER_TABLES | NOSAVE_ALLOWED_TABLES):
        stmts.append(f"GRANT {RW} ON `{schema}`.`{t}` TO '{api_user}'@'%'")
    stmts.append(f"GRANT SELECT, INSERT ON `{schema}`.`admin_audit` TO '{api_user}'@'%'")
    stmts.append(f"GRANT SELECT ON `{schema}`.`alembic_version` TO '{api_user}'@'%'")
    return stmts


def apply_grants(conn: Connection, schema: str, ingest_user: str, api_user: str) -> int:
    stmts = grant_statements(schema, ingest_user, api_user)
    for s in stmts:
        conn.execute(text(s))
    return len(stmts)
