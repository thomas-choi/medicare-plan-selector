"""No-save write guard (DESIGN §8.5): a SQLAlchemy `before_cursor_execute` hook that raises when an INSERT, UPDATE,
DELETE or REPLACE hits a user table while the current request is in No-save mode (test N2).

The only exception is an explicit, scoped allowance: the "Send a message to the team" form inserts one `feedback`
row with `session_id = NULL` (`allow_writes("feedback")`). Aggregates without linkage (`feedback_counter`,
`usage_daily`) are always allowed. `zip_county_cache` is guarded too: No-save lookups never fill caches.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Engine, event

from selector.models import USER_TABLES

GUARDED = USER_TABLES | {"zip_county_cache"}
_mode: ContextVar[str | None] = ContextVar("msp_request_mode", default=None)
_allowed: ContextVar[frozenset[str]] = ContextVar("msp_allowed_writes", default=frozenset())
_WRITE = re.compile(
    r"^\s*(?:INSERT|REPLACE)\s+(?:IGNORE\s+)?(?:INTO\s+)?`?(\w+)`?"
    r"|^\s*UPDATE\s+(?:IGNORE\s+)?`?(\w+)`?"
    r"|^\s*DELETE\s+(?:\w+\s+)?FROM\s+`?(\w+)`?",
    re.I,
)


class NoSaveWriteError(RuntimeError):
    """A No-save request tried to write a user table."""


def written_table(statement: str) -> str | None:
    m = _WRITE.match(statement)
    if not m:
        return None
    return next(g for g in m.groups() if g).lower()


def current_mode() -> str | None:
    return _mode.get()


@contextmanager
def request_mode(mode: str | None) -> Iterator[None]:
    token = _mode.set(mode)
    try:
        yield
    finally:
        _mode.reset(token)


@contextmanager
def allow_writes(*tables: str) -> Iterator[None]:
    token = _allowed.set(_allowed.get() | frozenset(tables))
    try:
        yield
    finally:
        _allowed.reset(token)


def check(statement: str) -> None:
    if _mode.get() != "nosave":
        return
    table = written_table(statement)
    if table in GUARDED and table not in _allowed.get():
        raise NoSaveWriteError(f"No-save request tried to write `{table}`")


def install(engine: Engine) -> Engine:
    if getattr(engine, "_msp_write_guard", False):
        return engine

    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        check(statement)

    engine._msp_write_guard = True  # type: ignore[attr-defined]
    return engine
