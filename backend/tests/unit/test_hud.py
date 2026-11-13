from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from selector.geo.hud import HudAuthError, HudClient

BASE = "https://hud.test/hudapi/public/usps"


def _client() -> HudClient:
    return HudClient("tok-test", BASE, httpx.Client(), min_interval_s=0)


@respx.mock
def test_zip_lookup_sorted_by_res_ratio_and_sends_bearer() -> None:
    route = respx.get(BASE).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "year": 2026,
                    "quarter": 3,
                    "results": [
                        {"geoid": "04021", "res_ratio": 0.12},
                        {"geoid": "04013", "res_ratio": 0.88},
                    ],
                }
            },  # fmt: skip
        )
    )
    out = _client().zip_counties("85142")
    assert [z.fips for z in out] == ["04013", "04021"]
    assert out[0].res_ratio == Decimal("0.88") and (out[0].hud_year, out[0].hud_quarter) == (2026, 3)
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer tok-test"
    assert req.url.params["type"] == "2" and req.url.params["query"] == "85142"


@respx.mock
def test_status_codes() -> None:
    respx.get(BASE).mock(return_value=httpx.Response(404))
    assert _client().zip_counties("00000") == []
    respx.get(BASE).mock(return_value=httpx.Response(403))
    with pytest.raises(HudAuthError):
        _client().zip_counties("85004")


def test_rejects_bad_input_and_missing_token() -> None:
    with pytest.raises(ValueError):
        _client().zip_counties("8500")
    with pytest.raises(ValueError):
        _client().state_counties("Arizona; DROP")
    with pytest.raises(HudAuthError):
        HudClient("", BASE)
