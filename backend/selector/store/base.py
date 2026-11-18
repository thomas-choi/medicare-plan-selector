"""`SessionStore` interface (DESIGN §8.5): `EphemeralSessionStore` (No-save, Redis only) and `MySQLSessionStore`
(Saved, encrypted at rest). The API picks the store from the session's mode; nothing else knows the difference."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from selector.agent.providers.base import ChatMessage
from selector.profile import Profile

CONSENT_VERSION = "2026-11-17"


def sid_hash(sid: bytes) -> str:
    return hashlib.sha256(sid).hexdigest()


@dataclass
class SessionHandle:
    """What the cookie carries: the raw 256-bit session id, the mode, and (No-save) the per-session key."""

    sid: bytes
    mode: str  # nosave | saved
    key: bytes | None = None

    @property
    def id_hash(self) -> str:
        return sid_hash(self.sid)


@dataclass
class SessionMeta:
    mode: str
    created_at: str
    expires_at: str
    consent_version: str
    plan_year: int
    consent_profile: bool = False
    consent_feedback_phi: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoredMessage:
    role: str
    content: str
    created_at: str
    model_id: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)

    def to_chat(self) -> ChatMessage:
        return ChatMessage("user" if self.role == "user" else "assistant", self.content)


class SessionExpired(LookupError):
    pass


class SessionStore(Protocol):
    mode: str

    def create(self, h: SessionHandle, meta: SessionMeta, ip_prefix_hash: str | None = None) -> None: ...
    def get_meta(self, h: SessionHandle) -> SessionMeta | None: ...
    def touch(self, h: SessionHandle) -> None: ...
    def load_profile(self, h: SessionHandle) -> Profile | None: ...
    def save_profile(self, h: SessionHandle, profile: Profile) -> None: ...
    def load_chat(self, h: SessionHandle) -> list[StoredMessage]: ...
    def append_chat(self, h: SessionHandle, msgs: list[StoredMessage], tokens: tuple[int, int] = (0, 0)) -> None: ...
    def load_canvas(self, h: SessionHandle) -> dict[str, Any]: ...
    def save_canvas(self, h: SessionHandle, canvas: dict[str, Any]) -> None: ...
    def save_recommendations(self, h: SessionHandle, rows: list[dict[str, Any]], data_vintage: str) -> list[str]: ...
    def end_soon(self, h: SessionHandle, grace_seconds: int) -> None: ...
    def delete(self, h: SessionHandle) -> int: ...


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def dumps(o: Any) -> bytes:
    return json.dumps(o, default=str, separators=(",", ":")).encode()
