"""Saved mode: encrypted columns hold ciphertext, chat/recommendations persist, delete-my-data leaves no
PHI rows, and the nightly retention purge."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, insert, select, update

from selector import models as m
from selector.api import cookies
from selector.store.mysql_store import purge_expired
from tests.api_support import SENTINEL_DOCTOR, SENTINEL_DRUG, SENTINEL_ZIP, chat, client, sentinel_profile, start

pytestmark = pytest.mark.infra


@pytest.fixture
def mig(fixture_db: dict[str, str]) -> Any:
    eng = create_engine(fixture_db["migrator"])
    yield eng
    eng.dispose()


def rows(eng: Engine, table: str, sid: str) -> list[dict[str, Any]]:
    t = m.metadata.tables[table]
    col = t.c.session_id_hash if table == "usage_ledger" else (t.c.id_hash if table == "session" else t.c.session_id)
    with eng.connect() as c:
        return [dict(r) for r in c.execute(select(t).where(col == sid)).mappings()]


def test_saved_session_is_encrypted_and_delete_my_data_removes_it(fixture_db: dict[str, str], mig: Engine) -> None:
    c = client(fixture_db)
    start(c, "saved")
    h = cookies.decode(c.cookies.get(cookies.COOKIE))
    assert h is not None and h.mode == "saved" and h.key is None
    assert c.put("/api/profile", json=sentinel_profile()).status_code == 200
    chat(c, f"compare plans, I take {SENTINEL_DRUG}")
    sid = h.id_hash
    assert len(rows(mig, "session", sid)) == 1 and len(rows(mig, "consent_log", sid)) == 1
    prof = rows(mig, "profile", sid)[0]
    msgs = rows(mig, "chat_msg", sid)
    recs = rows(mig, "recommendation", sid)
    assert len(msgs) == 2 and recs and recs[0]["rank_pos"] == 1
    blobs = [prof["zip_enc"], prof["drugs_enc"], prof["providers_enc"], *[x["content_enc"] for x in msgs]]
    for b in blobs:
        assert b and not any(s.encode() in b for s in (SENTINEL_ZIP, SENTINEL_DRUG, SENTINEL_DOCTOR))
    for jcol in ("budget_json", "utilization_json", "must_haves_json"):
        assert SENTINEL_DRUG not in str(prof[jcol])
    # resume: a new browser tab with the same cookie sees everything again
    got = c.get("/api/session").json()
    assert got["profile"]["drugs"][0]["name"] == SENTINEL_DRUG and len(got["chat"]) == 2

    resp = c.delete("/api/session")
    assert resp.json()["deleted"] and "Max-Age=0" in resp.headers["set-cookie"]
    for t in ("session", "profile", "chat_msg", "consent_log", "usage_ledger", "recommendation"):
        assert rows(mig, t, sid) == [], t
    with mig.connect() as conn:  # recommendation rows (no PHI) are kept, unlinked
        ids = [r["id"] for r in recs]
        kept = conn.execute(select(m.recommendation.c.session_id).where(m.recommendation.c.id.in_(ids))).all()
    assert kept and all(r[0] is None for r in kept)


def test_purge_expired_removes_idle_sessions_and_old_feedback(fixture_db: dict[str, str], mig: Engine) -> None:
    c = client(fixture_db)
    start(c, "saved")
    c.put("/api/profile", json=sentinel_profile())
    h = cookies.decode(c.cookies.get(cookies.COOKIE))
    assert h is not None
    old = dt.datetime(2020, 1, 1)
    with mig.begin() as conn:
        conn.execute(update(m.session).where(m.session.c.id_hash == h.id_hash).values(last_seen_at=old))
        conn.execute(insert(m.feedback).values(session_id=None, kind="general", text_redacted="old", mode="saved",
                                               app_version="t", prompt_version="v1", model_id="fake",
                                               created_at=old, phi_opt_in=False, triage_status="new"))  # fmt: skip
    eng = create_engine(fixture_db["api"])  # the purge runs as the API role
    with eng.begin() as conn:
        out = purge_expired(conn, 30, 365)
    eng.dispose()
    assert out["sessions"] >= 1 and out["feedback"] >= 1
    assert rows(mig, "session", h.id_hash) == [] and rows(mig, "profile", h.id_hash) == []
