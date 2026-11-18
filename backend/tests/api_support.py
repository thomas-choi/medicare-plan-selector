"""Helpers for API tests against the compose stack: an app on the scratch fixture schema with the fake LLM."""

from __future__ import annotations

import base64
import os
from typing import Any

from fastapi.testclient import TestClient

from selector.agent.providers import ChatProvider
from selector.agent.providers.fake import FakeProvider
from selector.api.main import create_app
from selector.config import Settings
from tests.conftest import REDIS_URL

TEST_PROFILE_KEY = base64.b64encode(os.urandom(32)).decode()

# Sentinels for N7/N8: they must never appear in logs or in raw Redis/MySQL values.
SENTINEL_ZIP = "99999"
SENTINEL_DRUG = "zzfakedrug"
SENTINEL_DOCTOR = "Dr Sentinel"


def settings(db: dict[str, str], **kw: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": db["api"],
        "ingest_database_url": db["ingest"],
        "migrator_database_url": db["migrator"],
        "redis_url": REDIS_URL,
        "llm_provider": "fake",
        "profile_enc_key": TEST_PROFILE_KEY,
        "cookie_secure": False,
        "max_sessions_per_ip_per_day": 1_000_000,  # tests start many sessions from one "IP"
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


def client(db: dict[str, str], providers: list[ChatProvider] | None = None, **kw: Any) -> TestClient:
    app = create_app(settings(db, **kw), providers=providers if providers is not None else [FakeProvider()],
                     lookups=False)  # fmt: skip
    return TestClient(app)


def sentinel_profile() -> dict[str, Any]:
    return {
        "zip": SENTINEL_ZIP,
        "county_ssa": "03060",
        "county_name": "Maricopa",
        "state": "AZ",
        "drugs": [{"name": SENTINEL_DRUG, "rxcui": "197361"}],
        "providers": [{"name": SENTINEL_DOCTOR}],
    }


def start(c: TestClient, mode: str = "nosave") -> dict[str, Any]:
    r = c.post("/api/session", json={"mode": mode, "consent_version": "2026-11-17", "accept_terms": True})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def chat(c: TestClient, message: str) -> list[tuple[str, str]]:
    r = c.post("/api/chat", json={"message": message})
    assert r.status_code == 200, r.text
    events = []
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], lines["data"]))
    return events
