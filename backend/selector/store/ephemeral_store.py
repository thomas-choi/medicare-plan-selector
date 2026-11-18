"""No-save session store (DESIGN §8.5). Everything lives in Redis under `eph:{sid_hash}:*`.

- Every value is AES-GCM encrypted with a per-session key that exists only in the user's cookie, so the server
  holds ciphertext it can't read once the cookie is gone (test N8).
- Sliding idle TTL (`EPHEMERAL_IDLE_MINUTES`) on every key, never past the absolute cap (`EPHEMERAL_MAX_HOURS`)
  stored in the meta record (test N4).
- `delete` removes every key (`DELETE /api/session`, test N3); the API start flushes all `eph:*` (test N5).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable
from typing import Any

import redis

from selector import crypto
from selector.profile import Profile
from selector.store.base import SessionExpired, SessionHandle, SessionMeta, StoredMessage, dumps

EPH_PREFIX = "eph:"
PARTS = ("meta", "profile", "chat", "canvas", "recs")
MAX_CHAT_MESSAGES = 200


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


class EphemeralSessionStore:
    mode = "nosave"

    def __init__(
        self,
        r: redis.Redis,
        idle_minutes: int,
        max_hours: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.r = r
        self.idle = idle_minutes * 60
        self.max = max_hours * 3600
        self.clock = clock

    @staticmethod
    def _k(h: SessionHandle, part: str) -> str:
        return f"{EPH_PREFIX}{h.id_hash}:{part}"

    def _key(self, h: SessionHandle) -> bytes:
        if not h.key:
            raise SessionExpired("missing session key")
        return h.key

    def _put(self, h: SessionHandle, part: str, value: Any, ttl: int) -> None:
        k = self._k(h, part)
        self.r.set(k, crypto.encrypt(self._key(h), dumps(value), k.encode()), ex=max(ttl, 1))

    def _get(self, h: SessionHandle, part: str) -> Any:
        k = self._k(h, part)
        blob = self.r.get(k)
        if blob is None:
            return None
        try:
            return json.loads(crypto.decrypt(self._key(h), bytes(blob), k.encode()))  # type: ignore[arg-type]
        except crypto.CryptoError as e:
            raise SessionExpired("cannot decrypt session") from e

    def _ttl(self, h: SessionHandle) -> int:
        """Remaining sliding TTL: min(idle, absolute deadline - now). Raises if the session is gone or expired."""
        raw = self.r.get(self._k(h, "deadline"))
        if raw is None:
            raise SessionExpired("no session")
        left = int(float(raw)) - int(self.clock())
        if left <= 0:
            self.delete(h)
            raise SessionExpired("absolute cap reached")
        return min(self.idle, left)

    def create(self, h: SessionHandle, meta: SessionMeta, ip_prefix_hash: str | None = None) -> None:
        deadline = int(self.clock()) + self.max
        ttl = min(self.idle, self.max)
        # The deadline itself is not secret (a timestamp); it carries the same TTL as the data.
        self.r.set(self._k(h, "deadline"), str(deadline), ex=ttl)
        meta.expires_at = dt.datetime.fromtimestamp(deadline, dt.UTC).isoformat()
        self._put(h, "meta", meta.as_dict(), ttl)

    def get_meta(self, h: SessionHandle) -> SessionMeta | None:
        try:
            self._ttl(h)
            d = self._get(h, "meta")
        except SessionExpired:
            return None
        return SessionMeta(**d) if d else None

    def touch(self, h: SessionHandle) -> None:
        ttl = self._ttl(h)
        pipe = self.r.pipeline()
        for part in (*PARTS, "deadline"):
            pipe.expire(self._k(h, part), ttl)
        pipe.execute()

    def load_profile(self, h: SessionHandle) -> Profile | None:
        self.touch(h)
        d = self._get(h, "profile")
        return Profile.model_validate(d) if d else None

    def save_profile(self, h: SessionHandle, profile: Profile) -> None:
        ttl = self._ttl(h)
        self._put(h, "profile", profile.model_dump(mode="json"), ttl)
        self.touch(h)

    def load_chat(self, h: SessionHandle) -> list[StoredMessage]:
        self.touch(h)
        return [StoredMessage(**m) for m in (self._get(h, "chat") or [])]

    def append_chat(self, h: SessionHandle, msgs: list[StoredMessage], tokens: tuple[int, int] = (0, 0)) -> None:
        cur = self._get(h, "chat") or []
        cur.extend(m.__dict__ for m in msgs)
        self._put(h, "chat", cur[-MAX_CHAT_MESSAGES:], self._ttl(h))
        self.touch(h)

    def load_canvas(self, h: SessionHandle) -> dict[str, Any]:
        self.touch(h)
        return self._get(h, "canvas") or {}

    def save_canvas(self, h: SessionHandle, canvas: dict[str, Any]) -> None:
        self._put(h, "canvas", canvas, self._ttl(h))
        self.touch(h)

    def save_recommendations(self, h: SessionHandle, rows: list[dict[str, Any]], data_vintage: str) -> list[str]:
        recs = [{"id": f"eph-{i}", "plan_key": r["plan_key"], "rank": r["rank"]} for i, r in enumerate(rows, 1)]
        self._put(h, "recs", recs, self._ttl(h))
        return [r["id"] for r in recs]

    def end_soon(self, h: SessionHandle, grace_seconds: int) -> None:
        """Tab closed (sendBeacon): expire everything after a short grace period unless the user comes back."""
        pipe = self.r.pipeline()
        for part in (*PARTS, "deadline"):
            pipe.expire(self._k(h, part), max(grace_seconds, 1))
        pipe.execute()

    def delete(self, h: SessionHandle) -> int:
        keys = list(self.r.scan_iter(match=f"{EPH_PREFIX}{h.id_hash}:*", count=100))
        return int(self.r.unlink(*keys)) if keys else 0
