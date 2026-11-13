from __future__ import annotations

from fastapi.testclient import TestClient

from selector import __version__
from selector.api.main import create_app
from selector.config import Settings


def test_health() -> None:
    client = TestClient(create_app(Settings()))
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_no_public_openapi_docs() -> None:
    client = TestClient(create_app(Settings()))
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
