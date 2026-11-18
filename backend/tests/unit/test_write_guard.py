"""N2 (unit part): the write guard parses SQL and raises for user-table writes in a No-save request context."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from selector.store import write_guard as wg


@pytest.mark.parametrize(
    ("sql", "table"),
    [
        ("INSERT INTO profile (a) VALUES (1)", "profile"),
        ("insert into `chat_msg` values (1)", "chat_msg"),
        ("REPLACE INTO session VALUES (1)", "session"),
        ("INSERT IGNORE INTO feedback VALUES (1)", "feedback"),
        ("UPDATE consent_log SET x=1", "consent_log"),
        ("DELETE FROM usage_ledger WHERE 1", "usage_ledger"),
        ("  UPDATE `recommendation` SET x=1", "recommendation"),
        ("SELECT * FROM profile", None),
    ],
)
def test_written_table(sql: str, table: str | None) -> None:
    assert wg.written_table(sql) == table


def test_guard_blocks_only_nosave_user_writes() -> None:
    eng = wg.install(create_engine("sqlite://"))
    with eng.begin() as c:
        c.execute(text("CREATE TABLE profile (a INT)"))
        c.execute(text("CREATE TABLE feedback (a INT)"))
        c.execute(text("CREATE TABLE feedback_counter (a INT)"))
    with wg.request_mode("nosave"):
        with pytest.raises(wg.NoSaveWriteError), eng.begin() as c:
            c.execute(text("INSERT INTO profile (a) VALUES (1)"))
        with pytest.raises(wg.NoSaveWriteError), eng.begin() as c:
            c.execute(text("INSERT INTO feedback (a) VALUES (1)"))
        with eng.begin() as c:  # aggregates without linkage are allowed
            c.execute(text("INSERT INTO feedback_counter (a) VALUES (1)"))
            assert c.execute(text("SELECT count(*) FROM profile")).scalar() == 0
        with wg.allow_writes("feedback"), eng.begin() as c:  # the explicit team-message opt-in
            c.execute(text("INSERT INTO feedback (a) VALUES (1)"))
    with wg.request_mode("saved"), eng.begin() as c:
        c.execute(text("INSERT INTO profile (a) VALUES (1)"))
    with eng.begin() as c:
        c.execute(text("INSERT INTO profile (a) VALUES (2)"))  # no request context (CLI jobs)
        assert c.execute(text("SELECT count(*) FROM profile")).scalar() == 2


def test_install_is_idempotent() -> None:
    eng = create_engine("sqlite://")
    assert wg.install(wg.install(eng)) is eng
