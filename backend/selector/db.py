"""Database engines. Each role gets its own URL (see `Settings`)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from selector.config import get_settings


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600, future=True)


@lru_cache
def api_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def ingest_engine() -> Engine:
    return make_engine(get_settings().effective_ingest_url)
