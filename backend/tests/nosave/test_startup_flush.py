"""Wipe trigger 5: the API start deletes every eph:* key and nothing else."""

from __future__ import annotations

import pytest
import redis

from selector.cli import main
from selector.store.ephemeral_store import flush_all_ephemeral
from tests.conftest import REDIS_URL

pytestmark = pytest.mark.infra


def test_flush_removes_only_ephemeral_keys() -> None:
    r = redis.Redis.from_url(REDIS_URL)
    for i in range(1200):
        r.set(f"eph:flushtest{i % 7}:k{i}", "x", ex=60)
    r.set("quota:flushtest", "1", ex=60)
    assert flush_all_ephemeral(r) >= 1200
    assert list(r.scan_iter(match="eph:*")) == []
    assert r.get("quota:flushtest") == b"1"
    r.delete("quota:flushtest")


def test_cli_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    r = redis.Redis.from_url(REDIS_URL)
    r.set("eph:clitest:a", "x", ex=60)
    assert main(["ephemeral-flush"]) == 0
    assert r.exists("eph:clitest:a") == 0
