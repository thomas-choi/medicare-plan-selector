"""Normalization helpers shared by the parsers: money → cents, percents, plan keys, stars, `src_ref`."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# "." is the SAS missing-value marker CMS uses in some fields (e.g. insulin TIER for defined-standard plans).
NOT_APPLICABLE = {"", ".", "not applicable", "n/a", "na", "none"}


def blank(v: str | None) -> bool:
    return v is None or v.strip().lower() in NOT_APPLICABLE


def money_to_cents(v: str | None) -> int | None:
    """'$1,234.50 ' → 123450. Blank / 'Not Applicable' → None. Rounds half-up to the cent."""
    if blank(v):
        return None
    assert v is not None
    s = v.strip().replace("$", "").replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"not a money value: {v!r}") from e
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fraction_to_pct(v: str | None) -> Decimal | None:
    """CMS fraction '.17' → Decimal('17.00') percent. Blank → None."""
    if blank(v):
        return None
    assert v is not None
    return (Decimal(v.strip()) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct_str_to_pct(v: str | None) -> Decimal | None:
    """PBP percent '20' or '20.00' → Decimal('20.00'). Blank → None."""
    if blank(v):
        return None
    assert v is not None
    return Decimal(v.strip().rstrip("%")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plan_key(contract_id: str, plan_id: str, segment_id: str | int) -> str:
    """Canonical key 'H0028_028_0' (Landscape style). S3 pads segments to '000'; PBP uses '0'."""
    c = contract_id.strip().upper()
    p = f"{int(plan_id):03d}"
    seg = int(str(segment_id).strip() or 0)
    if len(c) != 5:
        raise ValueError(f"bad contract id {contract_id!r}")
    return f"{c}_{p}_{seg}"


def star(v: str | None) -> tuple[Decimal | None, str | None]:
    """'4.5' → (Decimal('4.5'), None); 'Plan Too New To Be Measured' → (None, that text)."""
    if v is None or not v.strip():
        return None, None
    try:
        return Decimal(v.strip()), None
    except InvalidOperation:
        return None, v.strip()[:64]


def yn(v: str | None) -> bool:
    return (v or "").strip().upper() in {"Y", "YES", "1", "TRUE"}


def src_ref(source_id: str, vintage: str, row_key: str, **extra: Any) -> dict[str, Any]:
    ref: dict[str, Any] = {"source": source_id, "vintage": vintage, "row": row_key}
    ref.update(extra)
    return ref
