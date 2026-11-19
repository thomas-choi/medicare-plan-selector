"""Allowlist request logging (DESIGN §8.1, §8.5 Logs).

One line per request with only: request id (random, per request), method, path (no query string), status, duration.
Never: bodies, query strings, cookies, headers, session id or its hash, IP. Errors are logged by type only.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from selector.api import cookies
from selector.store import write_guard

log = logging.getLogger("selector.access")
ALLOWED_FIELDS = ("rid", "method", "path", "status", "ms")


class AccessLogMiddleware:
    """Also sets the No-save write-guard mode for the whole request from the cookie's mode flag. Requests without
    a valid cookie run as No-save too (the strictest mode); creating a Saved session opts out explicitly."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = os.urandom(6).hex()
        start = time.monotonic()
        status = 500
        raw = _cookie(scope)
        h = cookies.decode(raw)
        mode = h.mode if h else "nosave"

        async def _send(msg: Message) -> None:
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
                msg.setdefault("headers", [])
                msg["headers"].append((b"x-request-id", rid.encode()))
            await send(msg)

        try:
            with write_guard.request_mode(mode):
                await self.app(scope, receive, _send)
        except Exception as e:
            log.error("rid=%s error=%s", rid, type(e).__name__)
            raise
        finally:
            path = scope.get("path", "")
            if not path.startswith(("/api/health", "/api/ready")):
                log.info(
                    "rid=%s method=%s path=%s status=%s ms=%d",
                    rid,
                    scope.get("method"),
                    _safe_path(path),
                    status,
                    (time.monotonic() - start) * 1000,
                )


def _cookie(scope: Scope) -> str | None:
    for k, v in scope.get("headers", []):
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == cookies.COOKIE:
                    return str(val)
    return None


def _safe_path(path: str) -> str:
    """Paths carry no user data in this API, but cap the length and strip anything odd just in case."""
    p = "".join(ch for ch in path[:120] if ch.isalnum() or ch in "/_-.")
    return p or "/"


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # uvicorn's access log includes query strings; the entrypoint passes --no-access-log, this is belt and braces.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def extra_fields(**kw: Any) -> str:
    return " ".join(f"{k}={v}" for k, v in kw.items() if k in ALLOWED_FIELDS)
