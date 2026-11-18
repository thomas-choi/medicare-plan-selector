"""The `msp_sid` cookie (DESIGN §8.1, §8.5): `v1.<n|s>.<sid>[.<key>]`, base64url parts.

- `sid` is a random 256-bit value; the server stores only its SHA-256.
- No-save cookies also carry the 256-bit per-session AES key, so the server can't read the Redis data without it.
- The mode letter is the "non-identifying flag" the design allows; a forged letter just points at the other store,
  where the session doesn't exist.
"""

from __future__ import annotations

import os

from fastapi import Request, Response

from selector import crypto
from selector.config import Settings
from selector.store.base import SessionHandle

COOKIE = "msp_sid"
_MODES = {"n": "nosave", "s": "saved"}
_LETTER = {v: k for k, v in _MODES.items()}


def new_handle(mode: str) -> SessionHandle:
    return SessionHandle(os.urandom(32), mode, crypto.new_key() if mode == "nosave" else None)


def encode(h: SessionHandle) -> str:
    parts = ["v1", _LETTER[h.mode], crypto.b64u(h.sid)]
    if h.key:
        parts.append(crypto.b64u(h.key))
    return ".".join(parts)


def decode(value: str | None) -> SessionHandle | None:
    if not value or len(value) > 200:
        return None
    parts = value.split(".")
    if len(parts) not in (3, 4) or parts[0] != "v1" or parts[1] not in _MODES:
        return None
    mode = _MODES[parts[1]]
    try:
        sid = crypto.unb64u(parts[2])
        key = crypto.unb64u(parts[3]) if len(parts) == 4 else None
    except ValueError:
        return None
    if len(sid) != 32 or (mode == "nosave" and (key is None or len(key) != 32)) or (mode == "saved" and key):
        return None
    return SessionHandle(sid, mode, key)


def from_request(request: Request) -> SessionHandle | None:
    return decode(request.cookies.get(COOKIE))


def set_cookie(resp: Response, h: SessionHandle, s: Settings) -> None:
    # No-save: a browser-session cookie (gone when the browser closes). Saved: lives for RETENTION_DAYS.
    max_age = None if h.mode == "nosave" else s.retention_days * 86400
    resp.set_cookie(
        COOKIE, encode(h), max_age=max_age, httponly=True, secure=s.cookie_secure, samesite="lax", path="/api"
    )


def clear_cookie(resp: Response, s: Settings) -> None:
    resp.delete_cookie(COOKIE, path="/api", httponly=True, secure=s.cookie_secure, samesite="lax")
