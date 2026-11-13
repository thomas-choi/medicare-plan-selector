"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from selector import __version__
from selector.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Medicare Plan Selector",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory selector.api.main:app_factory`."""
    return create_app()
