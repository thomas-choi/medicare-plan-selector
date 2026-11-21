"""Per-app resources (engines, Redis, stores, LLM providers, lookup clients). Built once in `create_app`; tests
inject their own `Settings` (and optionally providers)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import redis
from sqlalchemy import Engine

from selector import crypto
from selector.agent.providers import ChatProvider, ProviderConfigError
from selector.agent.providers.factory import build_provider_chain
from selector.config import Settings
from selector.db import make_engine
from selector.geo.hud import HudClient
from selector.lookups import NppesClient, RxNavClient
from selector.network import DirectoryChecker, OptOutConfig
from selector.quotas import Quotas
from selector.store import write_guard
from selector.store.base import SessionHandle, SessionStore
from selector.store.ephemeral_store import EphemeralSessionStore
from selector.store.mysql_store import MySQLSessionStore

log = logging.getLogger(__name__)


@dataclass
class AppState:
    settings: Settings
    engine: Engine
    redis: redis.Redis
    ephemeral: EphemeralSessionStore
    saved: MySQLSessionStore | None
    providers: list[ChatProvider]
    hud: HudClient | None
    rxnav: RxNavClient | None
    nppes: NppesClient | None
    directory: DirectoryChecker | None = None
    quotas: Quotas | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def store(self, h: SessionHandle) -> SessionStore:
        if h.mode == "nosave":
            return self.ephemeral
        if self.saved is None:
            raise SavedModeUnavailable()
        return self.saved

    @property
    def llm_enabled(self) -> bool:
        return bool(self.providers)

    def llm_paused(self) -> bool:
        return self.quotas is not None and self.quotas.paused()


def _providers(s: Settings) -> list[ChatProvider]:
    """A misconfigured provider (say, a missing key) must not stop the app: it runs in no-LLM mode instead."""
    try:
        return build_provider_chain(s)
    except ProviderConfigError as e:
        log.error("LLM provider disabled: %s", e)
        return []


class SavedModeUnavailable(RuntimeError):
    """PROFILE_ENC_KEY isn't set, so Saved mode is off (the consent screen offers No-save only)."""


def build_state(
    s: Settings,
    *,
    providers: list[ChatProvider] | None = None,
    lookups: bool = True,
) -> AppState:
    engine = write_guard.install(make_engine(s.database_url))
    r = redis.Redis.from_url(s.redis_url, socket_timeout=5, socket_connect_timeout=5)
    saved = None
    try:
        key = crypto.profile_key(s)
    except crypto.CryptoError:
        key = None
    if key is not None:
        saved = MySQLSessionStore(engine, r, key, s.profile_key_version, s.retention_days)
    token = s.hud_api_token.get_secret_value()
    return AppState(
        quotas=Quotas(r, engine, s),
        settings=s,
        engine=engine,
        redis=r,
        ephemeral=EphemeralSessionStore(r, s.ephemeral_idle_minutes, s.ephemeral_max_hours),
        saved=saved,
        providers=_providers(s) if providers is None else providers,
        hud=HudClient(token, s.hud_api_base) if token and lookups else None,
        rxnav=RxNavClient() if lookups else None,
        nppes=NppesClient() if lookups else None,
        directory=DirectoryChecker(
            OptOutConfig(s.optout_url, s.optout_vintage),
            min_interval_s=s.directory_min_interval_s,
            budget_s=s.directory_budget_s,
        )
        if lookups
        else None,
    )
