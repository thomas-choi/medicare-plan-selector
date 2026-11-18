"""N3 (store part), N4 idle/absolute timeouts with a fake clock, N8 ciphertext at rest."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
import redis

from selector.api import cookies
from selector.profile import DrugIn, Profile, ProviderIn
from selector.store.base import SessionExpired, SessionMeta, StoredMessage
from selector.store.ephemeral_store import EphemeralSessionStore
from tests.api_support import SENTINEL_DOCTOR, SENTINEL_DRUG, SENTINEL_ZIP
from tests.conftest import REDIS_URL

pytestmark = pytest.mark.infra


class Clock:
    def __init__(self) -> None:
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def r() -> Iterator[redis.Redis]:
    c = redis.Redis.from_url(REDIS_URL)
    yield c
    c.close()


def meta() -> SessionMeta:
    return SessionMeta("nosave", "", "", "2026-11-17", 2027)


PROFILE = Profile(
    zip=SENTINEL_ZIP, drugs=[DrugIn(name=SENTINEL_DRUG, rxcui="1")], providers=[ProviderIn(name=SENTINEL_DOCTOR)]
)


def test_n8_values_are_ciphertext_and_need_the_cookie_key(r: redis.Redis) -> None:
    store = EphemeralSessionStore(r, 30, 4)
    h = cookies.new_handle("nosave")
    store.create(h, meta())
    store.save_profile(h, PROFILE)
    store.append_chat(h, [StoredMessage("user", f"I take {SENTINEL_DRUG}, ZIP {SENTINEL_ZIP}", "now")])
    keys = list(r.scan_iter(match=f"eph:{h.id_hash}:*"))
    assert len(keys) >= 3
    for k in keys:
        raw = r.get(k) or b""
        for s in (SENTINEL_ZIP, SENTINEL_DRUG, SENTINEL_DOCTOR):
            assert s.encode() not in raw
    assert store.load_profile(h) == PROFILE
    stranger = cookies.SessionHandle(h.sid, "nosave", cookies.new_handle("nosave").key)
    with pytest.raises(SessionExpired):
        store.load_profile(stranger)
    store.delete(h)


def test_n3_delete_removes_every_key(r: redis.Redis) -> None:
    store = EphemeralSessionStore(r, 30, 4)
    h = cookies.new_handle("nosave")
    store.create(h, meta())
    store.save_profile(h, PROFILE)
    store.save_canvas(h, {"tab": "table"})
    assert store.delete(h) >= 4
    assert list(r.scan_iter(match=f"eph:{h.id_hash}:*")) == []
    assert store.get_meta(h) is None


def test_n4_sliding_idle_ttl_capped_by_absolute_max(r: redis.Redis) -> None:
    clock = Clock()
    store = EphemeralSessionStore(r, idle_minutes=30, max_hours=1, clock=clock)
    h = cookies.new_handle("nosave")
    store.create(h, meta())
    store.save_profile(h, PROFILE)
    k = f"eph:{h.id_hash}:profile"
    assert 1700 < r.ttl(k) <= 1800  # idle TTL
    clock.t += 45 * 60  # 45 min later (activity keeps it alive): only 15 min left before the 1 h cap
    store.touch(h)
    assert 800 < r.ttl(k) <= 900  # activity extends, but never past the absolute cap
    clock.t += 16 * 60  # past the cap
    with pytest.raises(SessionExpired):
        store.touch(h)
    assert list(r.scan_iter(match=f"eph:{h.id_hash}:*")) == []


def test_n4_idle_expiry_for_real(r: redis.Redis) -> None:
    store = EphemeralSessionStore(r, 30, 4)
    store.idle = 1  # seconds, test only
    h = cookies.new_handle("nosave")
    store.create(h, meta())
    store.save_profile(h, PROFILE)
    time.sleep(2.2)
    assert list(r.scan_iter(match=f"eph:{h.id_hash}:*")) == []
    assert store.get_meta(h) is None


def test_end_soon_sets_short_grace_ttl(r: redis.Redis) -> None:
    store = EphemeralSessionStore(r, 30, 4)
    h = cookies.new_handle("nosave")
    store.create(h, meta())
    store.end_soon(h, 5)
    assert 0 < r.ttl(f"eph:{h.id_hash}:meta") <= 5
    store.touch(h)  # the user came back (reload): normal idle TTL again
    assert r.ttl(f"eph:{h.id_hash}:meta") > 60
    store.delete(h)
