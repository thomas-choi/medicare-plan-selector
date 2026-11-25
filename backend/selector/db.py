"""Database engines. Each role gets its own URL (see `Settings`)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine

from selector.config import get_settings


def db_connect_args(url: str) -> dict[str, Any]:
    """TLS with certificate and host-name checks when MSP_DB_CA_FILE is set (PyMySQL `ssl={"ca": ...}`).

    A URL that already carries `ssl_ca=` is left to its own settings."""
    ca = get_settings().db_ca_path
    if ca is None or "ssl_ca=" in url:
        return {}
    if not ca.is_file():
        raise RuntimeError(f"MSP_DB_CA_FILE: CA certificate not found at {ca}")
    return {"ssl": {"ca": str(ca)}}


def make_engine(
    url: str, *, write_timeout_s: int | None = None, read_timeout_s: int | None = None, session_sql: str | None = None
) -> Engine:
    """Engine for one role. The timeouts (PyMySQL socket timeouts) turn a stalled connection into an error;
    `session_sql` runs on every new connection (PyMySQL `init_command`)."""
    args = db_connect_args(url)
    if write_timeout_s:
        args["write_timeout"] = write_timeout_s
    if read_timeout_s:
        args["read_timeout"] = read_timeout_s
    if session_sql:
        args["init_command"] = session_sql
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600, future=True, connect_args=args)


def ingest_engine_for(url: str) -> Engine:
    """Engine for `selector ingest`, with the stall timeouts from the settings."""
    s = get_settings()
    # If our side drops a stuck connection, the server may not notice: by default it keeps an idle session for
    # wait_timeout (8 hours). Short server-side limits end such orphans within minutes; the ingest also KILLs them.
    idle = max(s.ingest_db_read_timeout_s, s.ingest_db_write_timeout_s) * 2
    session = f"SET SESSION wait_timeout={idle}, net_read_timeout={s.ingest_db_write_timeout_s * 2}"
    return make_engine(
        url,
        write_timeout_s=s.ingest_db_write_timeout_s,
        read_timeout_s=s.ingest_db_read_timeout_s,
        session_sql=session,
    )


@lru_cache
def api_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def ingest_engine() -> Engine:
    return make_engine(get_settings().effective_ingest_url)
