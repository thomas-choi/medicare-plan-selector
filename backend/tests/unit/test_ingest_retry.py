"""Batched ingest over an unreliable link: a dropped or stuck connection is closed and the batch retried."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pymysql  # type: ignore[import-untyped]
import pytest
from sqlalchemy.exc import OperationalError

from selector.ingest import load


def _err(code: int, msg: str = "boom") -> OperationalError:
    return OperationalError("INSERT ...", {}, pymysql.err.OperationalError(code, msg))


class FakeEngine:
    """`begin()` fails with the queued errors first, then succeeds; counts dispose() calls."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.disposed = 0
        self.runs = 0

    @contextmanager
    def begin(self) -> Iterator[object]:
        self.runs += 1
        if self.errors:
            raise self.errors.pop(0)
        yield object()

    def dispose(self) -> None:
        self.disposed += 1


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    return slept


def _run(engine: FakeEngine, **kw: Any) -> Any:
    return load._in_transaction(engine, "formulary rows 1-10,000", lambda c: "done", **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize("code", [2006, 2013, 2055, 1205])
def test_stuck_or_dropped_connection_is_retried_on_a_new_one(code: int, no_sleep: list[float]) -> None:
    eng = FakeEngine(_err(code), _err(code))
    assert _run(eng) == "done"
    assert (eng.runs, eng.disposed, no_sleep) == (3, 2, [5, 10])


def test_gives_up_after_the_configured_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_BATCH_ATTEMPTS", "3")
    from selector.config import Settings

    monkeypatch.setattr(load, "get_settings", lambda: Settings(_env_file=None))
    eng = FakeEngine(*[_err(2006) for _ in range(5)])
    with pytest.raises(OperationalError):
        _run(eng)
    assert eng.runs == 3


def test_other_errors_are_not_retried() -> None:
    eng = FakeEngine(_err(1146, "table missing"))
    with pytest.raises(OperationalError):
        _run(eng)
    assert (eng.runs, eng.disposed) == (1, 0)


def test_duplicate_key_on_a_retry_means_the_batch_had_committed() -> None:
    eng = FakeEngine(_err(2013), _err(1062, "Duplicate entry"))
    assert _run(eng, insert_batch=True) is None
    assert eng.runs == 2


def test_duplicate_key_on_the_first_try_is_a_real_error() -> None:
    with pytest.raises(OperationalError):
        _run(FakeEngine(_err(1062, "Duplicate entry")), insert_batch=True)


def test_only_the_ingest_engine_gets_stall_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    from selector import db

    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(db, "create_engine", lambda url, **kw: seen.append(kw["connect_args"]))
    db.ingest_engine_for("mysql+pymysql://u:p@h:25060/msp")
    db.make_engine("mysql+pymysql://u:p@h:25060/msp")
    assert seen[0]["write_timeout"] == 60 and seen[0]["read_timeout"] == 300
    assert seen[0]["init_command"] == "SET SESSION wait_timeout=600, net_read_timeout=120"
    assert "write_timeout" not in seen[1] and "read_timeout" not in seen[1]


class _Conn:
    """Looks enough like a SQLAlchemy connection over PyMySQL for `_server_thread_id` and KILL."""

    def __init__(self, tid: int, log: list[str]) -> None:
        self.tid, self.log = tid, log
        self.connection = self
        self.dbapi_connection = self

    def thread_id(self) -> int:
        return self.tid

    def exec_driver_sql(self, sql: str) -> None:
        self.log.append(sql)


class ThreadEngine(FakeEngine):
    """Every new connection gets the next server thread id; KILLs are recorded."""

    def __init__(self, *errors: Exception) -> None:
        super().__init__(*errors)
        self.next_tid, self.sql = 100, []  # type: ignore[var-annotated]

    @contextmanager
    def begin(self) -> Iterator[object]:
        self.runs += 1
        self.next_tid += 1
        conn = _Conn(self.next_tid, self.sql)
        if self.errors:
            err = self.errors.pop(0)
            # the error comes while the connection is in use, as with a stuck INSERT
            yield conn
            raise err
        yield conn

    @contextmanager
    def connect(self) -> Iterator[object]:
        yield _Conn(0, self.sql)


def test_retry_kills_the_stuck_server_session_first() -> None:
    eng = ThreadEngine(_err(2006), _err(2013))
    calls: list[int] = []

    def work(conn: Any) -> str:
        calls.append(conn.thread_id())
        return "done"

    assert load._in_transaction(eng, "formulary rows 1-1,000", work) == "done"  # type: ignore[arg-type]
    assert calls == [101, 102, 103] and eng.sql == ["KILL 101", "KILL 102"]


def test_hud_preload_without_a_token_explains_both_ways(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    from selector import cli
    from selector.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, hud_api_token=""))
    assert cli.main(["hud", "preload", "--state", "All"]) == 2
    err = capsys.readouterr().err
    assert "HUD_API_TOKEN is not set" in err and "make zip-data HUD_FILE=" in err


def test_zip_rows_are_stored_1000_per_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    from selector import cli, db
    from selector.geo import hud

    eng = FakeEngine()
    monkeypatch.setattr(db, "ingest_engine_for", lambda url: eng)
    sizes: list[int] = []
    monkeypatch.setattr(hud, "store_zip_counties", lambda conn, rows: sizes.append(len(rows)) or len(rows))
    assert cli._store_zip_rows([object()] * 2500) == 2500  # type: ignore[list-item]
    assert sizes == [1000, 1000, 500] and eng.runs == 3
