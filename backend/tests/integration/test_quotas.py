"""WP5: per-session turn/token limits, sessions per IP, the global daily budget (→ no-LLM mode), usage_daily for
all modes with no linkage, usage_ledger in Saved mode only, and the no-LLM /api/compare endpoint."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
import redis
from sqlalchemy import create_engine, delete, select

from selector import models as m
from selector.api import cookies
from tests.api_support import chat, client, sentinel_profile, start
from tests.conftest import REDIS_URL

pytestmark = pytest.mark.infra

# $5,000/Mtok: each fake completion (140 tokens) costs $0.70, so one demo turn (2 completions) spends $1.40 > $1.
PRICEY = {"llm_daily_budget_usd": 1.0, "llm_price_in_per_mtok_usd": 5_000, "llm_price_out_per_mtok_usd": 5_000}


@pytest.fixture(autouse=True)
def clean(fixture_db: dict[str, str]) -> Iterator[None]:
    """Fresh counters and ledgers for each test (the budget is per UTC day, shared across sessions)."""
    r = redis.Redis.from_url(REDIS_URL)

    def wipe() -> None:
        for k in r.scan_iter(match="quota:*"):
            r.delete(k)
        eng = create_engine(fixture_db["migrator"])
        with eng.begin() as c:
            c.execute(delete(m.usage_daily))
            c.execute(delete(m.usage_ledger))
        eng.dispose()

    wipe()
    yield
    wipe()


def test_turn_limit_then_form_still_works(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, max_turns_per_session=1)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    chat(c, "compare plans")
    r = c.post("/api/chat", json={"message": "again"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "session_turns"
    out = c.post("/api/compare", json={})
    assert out.status_code == 200
    body = out.json()
    assert body["top"][0]["plan_key"] and body["canvas"]["rows"] and body["checklist"]
    c.delete("/api/session")


def test_token_limit(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, max_tokens_per_session=50)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    chat(c, "compare plans")  # the fake provider reports 140 tokens per call
    r = c.post("/api/chat", json={"message": "again"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "session_tokens"
    c.delete("/api/session")


def test_sessions_per_ip(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, max_sessions_per_ip_per_day=2)
    start(c)
    start(c)
    r = c.post("/api/session", json={"mode": "nosave", "consent_version": "2026-11-17", "accept_terms": True})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "ip_sessions"
    rr = redis.Redis.from_url(REDIS_URL)
    keys = [k.decode() for k in rr.scan_iter(match="quota:ip:*")]
    assert keys and not any("testclient" in k or "127.0.0" in k for k in keys)  # hashed, not raw


def test_daily_budget_pauses_chat_and_keeps_form(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, **PRICEY)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    assert c.get("/api/config").json()["llm_enabled"] is True
    chat(c, "compare plans")
    assert c.get("/api/config").json()["llm_enabled"] is False
    r = c.post("/api/chat", json={"message": "again"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "no_llm"
    assert c.post("/api/compare", json={}).status_code == 200
    c.delete("/api/session")


def test_budget_survives_redis_loss_via_usage_daily(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, **PRICEY)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    chat(c, "compare plans")
    rr = redis.Redis.from_url(REDIS_URL)
    for k in rr.scan_iter(match="quota:budget:*"):
        rr.delete(k)
    assert c.get("/api/config").json()["llm_enabled"] is False  # re-seeded from usage_daily
    c.delete("/api/session")


def test_ledgers_by_mode(fixture_db: dict[str, str]) -> None:
    mig = create_engine(fixture_db["migrator"])
    ns = client(fixture_db)
    start(ns)
    ns.put("/api/profile", json=sentinel_profile())
    chat(ns, "compare plans")
    ns_hash = cookies.decode(ns.cookies.get(cookies.COOKIE)).id_hash  # type: ignore[union-attr]
    with mig.connect() as conn:
        daily = conn.execute(select(m.usage_daily)).mappings().all()
        ledger = conn.execute(select(m.usage_ledger)).mappings().all()
    assert daily and {d["mode"] for d in daily} == {"nosave"} and daily[0]["day"] == dt.datetime.now(dt.UTC).date()
    assert ledger == []  # No-save: no per-session ledger
    assert ns_hash not in str(daily)

    sv = client(fixture_db)
    start(sv, "saved")
    sv.put("/api/profile", json=sentinel_profile())
    chat(sv, "compare plans")
    sv_hash = cookies.decode(sv.cookies.get(cookies.COOKIE)).id_hash  # type: ignore[union-attr]
    with mig.connect() as conn:
        ledger = conn.execute(select(m.usage_ledger)).mappings().all()
        modes = {d["mode"] for d in conn.execute(select(m.usage_daily)).mappings()}
    assert ledger and all(row["session_id_hash"] == sv_hash for row in ledger) and ledger[0]["ip_prefix_hash"]
    assert modes == {"nosave", "saved"}
    sv.delete("/api/session")  # delete-my-data removes the ledger rows too
    with mig.connect() as conn:
        assert conn.execute(select(m.usage_ledger)).all() == []
    ns.delete("/api/session")
    mig.dispose()


def test_compare_without_llm_and_with_inline_profile(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, providers=[], llm_provider="")
    start(c)
    assert c.get("/api/config").json()["llm_enabled"] is False
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 503
    r = c.post("/api/compare", json={"profile": sentinel_profile() | {"zip": "85004"}, "limit": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["top"]) == 3 and body["top"][0]["plan_key"] == "H0028_028_0"
    assert "S1" in body["data_vintage"]
    assert c.get("/api/session").json()["profile"]["zip"] == "85004"
    empty = client(fixture_db, providers=[])
    start(empty)
    assert empty.post("/api/compare", json={}).json()["detail"]["code"] == "profile_incomplete"
    c.delete("/api/session")
    empty.delete("/api/session")


def test_budget_stops_a_turn_midway(fixture_db: dict[str, str]) -> None:
    c = client(fixture_db, llm_daily_budget_usd=1.0, llm_price_in_per_mtok_usd=10_000, llm_price_out_per_mtok_usd=0)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    r = c.post("/api/chat", json={"message": "compare plans"})  # the first completion alone spends $1
    assert r.status_code == 429 and r.json()["detail"]["code"] == "budget"
    c.delete("/api/session")
