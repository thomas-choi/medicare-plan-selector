from __future__ import annotations

from decimal import Decimal

import pytest

from selector.ingest.normalize import fraction_to_pct, money_to_cents, pct_str_to_pct, plan_key, star


@pytest.mark.parametrize(
    ("raw", "cents"),
    [
        ("$0.00 ", 0),
        ("$325.00 ", 32500),
        ("$6,550.00 ", 655000),
        ("$2,400.00 ", 240000),
        ("16.76", 1676),
        ("0.005", 1),  # half-up rounding
        ("Not Applicable", None),
        ("", None),
        (None, None),
    ],
)
def test_money_to_cents(raw: str | None, cents: int | None) -> None:
    assert money_to_cents(raw) == cents


def test_money_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        money_to_cents("about ten dollars")


def test_percents() -> None:
    assert fraction_to_pct("0.17") == Decimal("17.00")
    assert fraction_to_pct(".25") == Decimal("25.00")
    assert fraction_to_pct(" ") is None
    assert pct_str_to_pct("20") == Decimal("20.00")


@pytest.mark.parametrize(
    ("args", "key"),
    [
        (("H0028", "028", "0"), "H0028_028_0"),
        (("H0028", "028", "000"), "H0028_028_0"),
        (("S1030", "1", "0"), "S1030_001_0"),
        (("h0028", "028", "2"), "H0028_028_2"),
    ],
)
def test_plan_key(args: tuple[str, str, str], key: str) -> None:
    assert plan_key(*args) == key


def test_star() -> None:
    assert star("4.5") == (Decimal("4.5"), None)
    assert star("Plan Too New To Be Measured") == (None, "Plan Too New To Be Measured")
    assert star("") == (None, None)


def test_sas_missing_marker_is_blank() -> None:
    from selector.ingest.normalize import blank

    assert blank(".")
    assert money_to_cents(".") is None
