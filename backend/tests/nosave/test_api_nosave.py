"""No-save through the API: N2 (write guard on the real API engine), N3 end purge + cookie cleared, N5 restart,
N7 log sentinels, N8 raw Redis values, and the No-save chat leaving MySQL user tables untouched."""

from __future__ import annotations

import json
import logging

import pytest
import redis
from sqlalchemy import create_engine, func, select, text

from selector import models as m
from selector.api import cookies
from selector.store import write_guard
from selector.store.ephemeral_store import flush_all_ephemeral
from tests.api_support import (
    SENTINEL_DOCTOR,
    SENTINEL_DRUG,
    SENTINEL_ZIP,
    chat,
    client,
    sentinel_profile,
    start,
)
from tests.conftest import REDIS_URL

pytestmark = pytest.mark.infra
SENTINELS = (SENTINEL_ZIP, SENTINEL_DRUG, SENTINEL_DOCTOR)


def user_counts(url: str) -> dict[str, int]:
    eng = create_engine(url)
    with eng.connect() as c:
        out = {t: int(c.execute(select(func.count()).select_from(m.metadata.tables[t])).scalar_one())
               for t in sorted(m.USER_TABLES)}  # fmt: skip
    eng.dispose()
    return out


def test_n2_forced_insert_raises_on_api_engine(fixture_db: dict[str, str]) -> None:
    eng = write_guard.install(create_engine(fixture_db["api"]))
    with write_guard.request_mode("nosave"), pytest.raises(write_guard.NoSaveWriteError), eng.begin() as c:
        c.execute(text("INSERT INTO profile (session_id, key_version) VALUES ('x', 1)"))
    eng.dispose()


def test_nosave_flow_writes_no_user_rows_and_logs_no_sentinels(
    fixture_db: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    before = user_counts(fixture_db["migrator"])
    c = client(fixture_db)
    caplog.set_level(logging.DEBUG)
    body = start(c)
    assert body["session"]["mode"] == "nosave"
    raw_cookie = c.cookies.get(cookies.COOKIE)
    h = cookies.decode(raw_cookie)
    assert h is not None and h.mode == "nosave" and h.key
    assert c.put("/api/profile", json=sentinel_profile()).status_code == 200
    events = chat(c, f"Compare plans for me. I take {SENTINEL_DRUG} and see {SENTINEL_DOCTOR} in {SENTINEL_ZIP}.")
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and "delta" in kinds and "canvas" in kinds and kinds[-1] == "done"
    canvas = json.loads(next(d for e, d in events if e == "canvas"))
    assert canvas["rows"] and canvas["top"]
    got = c.get("/api/session").json()
    assert got["profile"]["zip"] == SENTINEL_ZIP and len(got["chat"]) == 2 and got["canvas"]["rows"]

    # N8: raw Redis values hold no sentinels
    r = redis.Redis.from_url(REDIS_URL)
    keys = list(r.scan_iter(match=f"eph:{h.id_hash}:*"))
    assert keys
    for k in keys:
        raw = r.get(k) or b""
        assert not any(s.encode() in raw for s in SENTINELS)

    # N3: end session & erase
    resp = c.delete("/api/session")
    assert resp.status_code == 200
    assert cookies.COOKIE in resp.headers.get("set-cookie", "") and "Max-Age=0" in resp.headers["set-cookie"]
    assert list(r.scan_iter(match=f"eph:{h.id_hash}:*")) == []

    # zero rows in MySQL user tables (the full N1 incl. feedback lands with WP6)
    assert user_counts(fixture_db["migrator"]) == before
    # N7: no sentinel in any log record
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "path=/api/chat" in logs
    assert not any(s in logs for s in SENTINELS)
    assert h.id_hash not in logs and raw_cookie not in logs


def test_n5_restart_flushes_and_old_cookie_gets_fresh_session(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    old = cookies.decode(c.cookies.get(cookies.COOKIE))
    assert old is not None
    r = redis.Redis.from_url(REDIS_URL)
    flush_all_ephemeral(r)  # what the entrypoint does on every API start
    assert list(r.scan_iter(match="eph:*")) == []
    c2 = client(fixture_db)  # "restarted" API
    c2.cookies.set(cookies.COOKIE, cookies.encode(old), domain="testserver.local", path="/api")
    got = c2.get("/api/session").json()
    assert got["renewed"] is True and got["profile"] is None and got["session"]["mode"] == "nosave"
    new = cookies.decode(c2.cookies.get(cookies.COOKIE))
    assert new is not None and new.sid != old.sid
    c2.delete("/api/session")


def test_requests_without_session_are_rejected(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    assert c.get("/api/session").json() == {"session": None}
    assert c.put("/api/profile", json={}).status_code == 401
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 401
    cfg = c.get("/api/config").json()
    assert cfg["default_mode"] == "nosave" and cfg["modes"] == ["nosave", "saved"] and cfg["llm_enabled"]
    assert cfg["checklist"] and cfg["llm_provider_label"]
    assert [g["title"] for g in cfg["glossary"]][:2] == ["Est. yearly cost", "Worst case"]


def test_ns4_config_defaults_to_nosave_while_saved_is_offered(
    fixture_db: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """NS4 (DESIGN v0.5 B2.5): with PROFILE_ENC_KEY set, Saved is offered but the default stays No-save, and an
    environment asking for Saved cannot change that (the settings refuse it)."""
    c = client(fixture_db)
    assert c.app.state.settings.profile_enc_key.get_secret_value()  # type: ignore[attr-defined]
    cfg = c.get("/api/config").json()
    assert cfg["modes"] == ["nosave", "saved"] and cfg["default_mode"] == "nosave"
    monkeypatch.setenv("DEFAULT_SESSION_MODE", "saved")
    with pytest.raises(ValueError, match="DESIGN v0.5 B2"):
        client(fixture_db)


def test_validation_errors_never_echo_input(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    start(c)
    bad = sentinel_profile() | {"zip": f"{SENTINEL_DRUG}"}
    r = c.put("/api/profile", json=bad)
    assert r.status_code == 422 and SENTINEL_DRUG not in r.text
    c.delete("/api/session")


def test_location_and_counties(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db)
    start(c)
    loc = c.get("/api/location", params={"zip": "85142"}).json()
    assert {o["ssa_code"] for o in loc["counties"]} == {"03060", "03100"}
    miss = c.get("/api/location", params={"zip": "99999"}).json()
    assert miss["counties"] == [] and miss["note"]
    az = c.get("/api/counties", params={"state": "az"}).json()["counties"]
    assert any(o["county"].startswith("Maricopa") for o in az)
    c.delete("/api/session")


def test_message_limit(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, max_message_chars=50)
    start(c)
    assert c.post("/api/chat", json={"message": "x" * 51}).status_code == 422
    c.delete("/api/session")
