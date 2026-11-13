"""N6: Redis keeps nothing on disk and comes back empty after a restart (DESIGN §8.5)."""

from __future__ import annotations

import time

import pytest
import redis

from tests.conftest import REDIS_URL, compose

pytestmark = pytest.mark.infra


def _client() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _wait_ready(timeout: float = 30) -> redis.Redis:
    deadline = time.monotonic() + timeout
    while True:
        try:
            r = _client()
            r.ping()
            return r
        except redis.ConnectionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def test_n6_persistence_is_off() -> None:
    r = _client()
    assert r.config_get("save") == {"save": ""}
    assert r.config_get("appendonly") == {"appendonly": "no"}


def test_n6_data_dir_is_tmpfs_and_has_no_dump_files() -> None:
    r = _client()
    r.set("eph:n6probe:x", "1", ex=60)
    # A forced BGSAVE must not be configured to happen; check the data dir itself.
    mounts = compose("exec", "-T", "redis", "sh", "-c", "grep ' /data ' /proc/mounts").stdout
    assert "tmpfs" in mounts
    listing = compose("exec", "-T", "redis", "ls", "-A", "/data").stdout.split()
    assert not [f for f in listing if f == "dump.rdb" or f.startswith("appendonly")]


def test_n6_restart_comes_back_empty() -> None:
    r = _client()
    r.set("eph:n6probe:y", "1", ex=600)
    assert r.dbsize() >= 1
    compose("restart", "redis")
    r = _wait_ready()
    assert r.dbsize() == 0
