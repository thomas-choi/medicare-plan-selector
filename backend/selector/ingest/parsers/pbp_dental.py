"""S2 CMS PBP Benefits, section 16 dental (`pbp_b16_dental.txt`, tab-delimited). Design v0.4 addendum A4.

One row per plan segment. Field meanings from `PBP_Benefits_2027_dictionary.xlsx` (file `pbp_b16_dental`):

| field | meaning |
|---|---|
| `pbp_b16a_{copay,coins}_mc_*` | 16a Medicare-covered dental cost sharing |
| `pbp_b16b_maxplan_pv_yn/_amt/_per` | 16b preventive: maximum plan benefit (1 = yes), amount, periodicity |
| `pbp_b16c_maxplan_cmp_yn/_type/_amt/_per` | 16c comprehensive maximum; type 1 = shared with 16b, 2 = own amount |
| `pbp_b16{b,c}_bendesc_<svc>_amo` | service offered as 2 = mandatory, 3 = optional supplemental, 4 = both |
| `pbp_b16{b,c}_bendesc_<svc>_desc` | CMS free-text limits (kept for display only, ≤512 chars) |
| `pbp_b16{b,c}_{copay,coins}_<svc>_yn` | 1 = yes, 2 = no, 3 = yes with a min and max |
| `*_per` | periodicity: 1 = 3 years, 2 = 2 years, 3 = year, 4 = 6 months, 5 = 3 months, 6 = other, 7 = month |
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from selector.ingest.normalize import blank, money_to_cents, pct_str_to_pct, plan_key, src_ref
from selector.ingest.parsers import HeaderMismatch, read_delimited

SOURCE = "S2"
FILE = "pbp_b16_dental.txt"

PERIOD = {"1": "3y", "2": "2y", "3": "year", "4": "6m", "5": "3m", "6": "other", "7": "month"}
PERIOD_TEXT = {"3y": "every 3 years", "2y": "every 2 years", "year": "/yr", "6m": "every 6 months",
               "3m": "every 3 months", "other": "(see plan)", "month": "/month"}  # fmt: skip
# Multiplier to a yearly amount (for the "dental maximum at least $X" must-have).
PER_YEAR = {"3y": Decimal(1) / 3, "2y": Decimal(1) / 2, "year": Decimal(1), "6m": Decimal(2), "3m": Decimal(4),
            "month": Decimal(12), "other": Decimal(1)}  # fmt: skip

PREVENTIVE: dict[str, str] = {
    "oe": "Oral exams",
    "dx": "Dental X-rays",
    "ods": "Other diagnostic services",
    "pc": "Cleanings",
    "ft": "Fluoride treatment",
    "ops": "Other preventive services",
}
COMPREHENSIVE: dict[str, str] = {
    "rs": "Fillings and crowns (restorative)",
    "end": "Root canals (endodontics)",
    "peri": "Gum care (periodontics)",
    "prm": "Dentures (removable prosthodontics)",
    "mxpr": "Maxillofacial prosthetics",
    "impl": "Implants",
    "prf": "Bridges (fixed prosthodontics)",
    "omsg": "Extractions and oral surgery",
    "orth": "Orthodontics",
    "ags": "Other services (anesthesia, emergency care)",
}
KEY_COLS = ("pbp_a_hnumber", "pbp_a_plan_identifier", "segment_id")
REQUIRED = (
    *KEY_COLS,
    "pbp_b16a_copay_mc_yn", "pbp_b16a_coins_mc_yn",
    "pbp_b16b_maxplan_pv_yn", "pbp_b16b_maxplan_pv_amt", "pbp_b16b_maxplan_pv_per",
    "pbp_b16c_maxplan_cmp_yn", "pbp_b16c_maxplan_cmp_type", "pbp_b16c_maxplan_cmp_amt", "pbp_b16c_maxplan_cmp_per",
    *(f"pbp_b16b_bendesc_{s}_amo" for s in PREVENTIVE),
    *(f"pbp_b16c_bendesc_{s}_amo" for s in COMPREHENSIVE),
)  # fmt: skip


def _get(r: dict[str, str], k: str) -> str:
    return (r.get(k) or "").strip()


def _cost(r: dict[str, str], prefix: str, svc: str) -> dict[str, Any]:
    """Copay (cents) and coinsurance (percent) min/max for one service; None where the plan has none."""
    out: dict[str, Any] = {"copay_min_cents": None, "copay_max_cents": None, "coins_min_pct": None,
                           "coins_max_pct": None}  # fmt: skip
    if _get(r, f"{prefix}_copay_{svc}_yn") in ("1", "3"):
        one = money_to_cents(_get(r, f"{prefix}_copay_{svc}_amt") or None)
        lo = money_to_cents(_get(r, f"{prefix}_copay_{svc}_amt_min") or None)
        hi = money_to_cents(_get(r, f"{prefix}_copay_{svc}_amt_max") or None)
        out["copay_min_cents"] = lo if lo is not None else one
        out["copay_max_cents"] = hi if hi is not None else (one if one is not None else lo)
    if _get(r, f"{prefix}_coins_{svc}_yn") in ("1", "3"):
        one_p = pct_str_to_pct(_get(r, f"{prefix}_coins_{svc}_pct") or None)
        lo_p = pct_str_to_pct(_get(r, f"{prefix}_coins_{svc}_pct_min") or None)
        hi_p = pct_str_to_pct(_get(r, f"{prefix}_coins_{svc}_pct_max") or None)
        lo_v = lo_p if lo_p is not None else one_p
        hi_v = hi_p if hi_p is not None else (one_p if one_p is not None else lo_p)
        out["coins_min_pct"] = float(lo_v) if lo_v is not None else None
        out["coins_max_pct"] = float(hi_v) if hi_v is not None else None
    return out


def cost_text(c: dict[str, Any]) -> str:
    """'$0', '$0–$50', '50%', '0–50%', '$20 + 0–50%'. No cost sharing listed → '$0'."""
    parts: list[str] = []
    lo, hi = c.get("copay_min_cents"), c.get("copay_max_cents")
    if lo is not None or hi is not None:
        a, b = lo if lo is not None else hi, hi if hi is not None else lo
        assert a is not None and b is not None
        parts.append(f"${a / 100:,.0f}" if a == b else f"${a / 100:,.0f}–${b / 100:,.0f}")
    plo, phi = c.get("coins_min_pct"), c.get("coins_max_pct")
    if plo is not None or phi is not None:
        a2, b2 = plo if plo is not None else phi, phi if phi is not None else plo
        assert a2 is not None and b2 is not None
        parts.append(f"{a2:g}%" if a2 == b2 else f"{a2:g}–{b2:g}%")
    return " + ".join(parts) if parts else "$0"


def combined(services: list[dict[str, Any]]) -> dict[str, Any]:
    """The overall cost range across services (min of minimums, max of maximums)."""

    def pick(key: str, fn: Any) -> Any:
        vals = [s[key] for s in services if s.get(key) is not None]
        return fn(vals) if vals else None

    return {"copay_min_cents": pick("copay_min_cents", min), "copay_max_cents": pick("copay_max_cents", max),
            "coins_min_pct": pick("coins_min_pct", min), "coins_max_pct": pick("coins_max_pct", max)}  # fmt: skip


def _services(r: dict[str, str], prefix: str, codes: dict[str, str], group: str) -> list[dict[str, Any]]:
    out = []
    for code, label in codes.items():
        amo = _get(r, f"{prefix}_bendesc_{code}_amo")
        if amo not in ("2", "3", "4"):
            continue
        c = _cost(r, prefix, code)
        limit = _get(r, f"{prefix}_bendesc_{code}_desc") or None
        out.append({"code": code, "label": label, "group": group, "mandatory": amo in ("2", "4"),
                    "optional": amo in ("3", "4"), **c, "cost": cost_text(c),
                    "limit_text": limit[:512] if limit else None})  # fmt: skip
    return out


def _period(r: dict[str, str], field: str) -> str | None:
    return PERIOD.get(_get(r, field)) if not blank(_get(r, field)) else None


def parse_dental(text: str, vintage: str) -> Iterator[dict[str, Any]]:
    """Yields one `plan_dental` row (without plan_year) per plan segment in the file."""
    rows = read_delimited(text, "\t")
    checked = False
    for r in rows:
        if not checked:
            missing = [c for c in REQUIRED if c not in r]
            if missing:
                raise HeaderMismatch(f"PBP b16 missing columns {missing}")
            checked = True
        key = plan_key(r["pbp_a_hnumber"], r["pbp_a_plan_identifier"], r["segment_id"])
        prev = _services(r, "pbp_b16b", PREVENTIVE, "preventive")
        comp = _services(r, "pbp_b16c", COMPREHENSIVE, "comprehensive")
        mc = {"copay": _get(r, "pbp_b16a_copay_mc_yn"), "coins": _get(r, "pbp_b16a_coins_mc_yn")}
        pv_max = comp_max = None
        pv_per = comp_per = None
        shared: bool | None = None
        if _get(r, "pbp_b16b_maxplan_pv_yn") == "1":
            pv_max = money_to_cents(_get(r, "pbp_b16b_maxplan_pv_amt") or None)
            pv_per = _period(r, "pbp_b16b_maxplan_pv_per")
        if _get(r, "pbp_b16c_maxplan_cmp_yn") == "1":
            if _get(r, "pbp_b16c_maxplan_cmp_type") == "1":
                shared = True
            else:
                shared = False
                comp_max = money_to_cents(_get(r, "pbp_b16c_maxplan_cmp_amt") or None)
                comp_per = _period(r, "pbp_b16c_maxplan_cmp_per")
        services = prev + comp
        if mc["copay"] in ("1", "3") or mc["coins"] in ("1", "3"):
            c = _cost(r, "pbp_b16a", "mc")
            services.insert(0, {"code": "mc", "label": "Medicare-covered dental", "group": "medicare_covered",
                                "mandatory": True, "optional": False, **c, "cost": cost_text(c),
                                "limit_text": None})  # fmt: skip
        yield {
            "plan_key": key,
            "has_medicare_covered": any(v in ("1", "2", "3") for v in mc.values()),
            "has_preventive": any(s["mandatory"] for s in prev),
            "has_comprehensive": any(s["mandatory"] for s in comp),
            "preventive_max_cents": pv_max,
            "preventive_max_period": pv_per,
            "comprehensive_max_cents": comp_max,
            "comprehensive_max_period": comp_per,
            "comprehensive_max_shared": shared,
            "optional_supplemental": any(s["optional"] for s in prev + comp),
            "services_json": services,
            "src_ref": src_ref(SOURCE, vintage, f"b16:{key}"),
        }
