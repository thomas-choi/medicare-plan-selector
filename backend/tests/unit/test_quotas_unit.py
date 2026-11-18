"""Quota helpers that need no stack: IP prefixes and the cost formula."""

from __future__ import annotations

from typing import Any

import pytest

from selector.agent.providers import Usage
from selector.config import Settings
from selector.quotas import Quotas, ip_prefix


@pytest.mark.parametrize(
    ("ip", "prefix"),
    [
        ("203.0.113.77", "203.0.113.0/24"),
        ("2001:db8:abcd:12::1", "2001:db8:abcd::/48"),
        ("not-an-ip", "unknown"),
        (None, "unknown"),
    ],
)
def test_ip_prefix(ip: str | None, prefix: str) -> None:
    assert ip_prefix(ip) == prefix


def test_cost_micro_usd() -> None:
    s = Settings(_env_file=None, llm_price_in_per_mtok_usd=3.0, llm_price_out_per_mtok_usd=15.0)
    q: Any = Quotas(r=None, engine=None, settings=s)  # type: ignore[arg-type]
    assert q.cost_micro_usd(Usage(1000, 500)) == 3000 + 7500  # $0.0105


def test_blank_prices_cost_nothing() -> None:
    s = Settings(_env_file=None, llm_price_in_per_mtok_usd="", llm_price_out_per_mtok_usd="")
    q: Any = Quotas(r=None, engine=None, settings=s)  # type: ignore[arg-type]
    assert q.cost_micro_usd(Usage(10**6, 10**6)) == 0
