"""FastAPI application factory."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from selector import __version__
from selector.agent.providers import ChatProvider
from selector.api import feedback_routes
from selector.api.logging_mw import AccessLogMiddleware, configure_logging
from selector.api.routes import router
from selector.api.state import AppState, build_state
from selector.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    *,
    providers: list[ChatProvider] | None = None,
    lookups: bool = True,
    state: AppState | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    app = FastAPI(title="Medicare Plan Selector", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.msp = state or build_state(settings, providers=providers, lookups=lookups)
    app.add_middleware(AccessLogMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only; never echo the submitted values (they may be PHI).
        errs: list[dict[str, Any]] = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse({"detail": {"code": "invalid", "errors": errs}}, status_code=422)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(router)
    app.include_router(feedback_routes.router)
    app.state.msp.extras.setdefault("feedback_hook", feedback_routes.agent_feedback_hook)
    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory selector.api.main:app_factory`."""
    return create_app()
