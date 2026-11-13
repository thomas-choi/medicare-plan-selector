"""No-save session store (DESIGN §8.5). Everything lives in Redis under `eph:{sid_hash}:*`."""

from __future__ import annotations

import redis

EPH_PREFIX = "eph:"


def flush_all_ephemeral(r: redis.Redis) -> int:
    """Delete every `eph:*` key. Runs once per API container start (wipe trigger 5)."""
    deleted = 0
    batch: list[bytes | str] = []
    for key in r.scan_iter(match=f"{EPH_PREFIX}*", count=500):
        batch.append(key)
        if len(batch) >= 500:
            deleted += int(r.unlink(*batch))
            batch.clear()
    if batch:
        deleted += int(r.unlink(*batch))
    return deleted
