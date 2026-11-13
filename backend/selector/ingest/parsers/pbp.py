"""S2 CMS PBP Benefits (tab-delimited). Minimal MVP mapping, approved by Thomas 2026-11-12:

| service_code | PBP section | fields (Medicare-covered, in network) |
|---|---|---|
| pcp | b7a | pbp_b7a_copay_amt_mc_min/max, pbp_b7a_coins_pct_mc_min/max |
| specialist | b7d | pbp_b7d_copay_amt_mc_min/max, pbp_b7d_coins_pct_mc_min/max |
| er | b4a | pbp_b4a_copay_amt_mc_min/max, pbp_b4a_coins_pct_mc_min/max |
| urgent_care | b4b | pbp_b4b_copay_amt_mc_min/max, pbp_b4b_coins_pct_mc_min/max |
| outpatient | b9a | pbp_b9a_copay_ohs_amt_min/max, pbp_b9a_coins_ohs_pct_min/max |

Ranges keep min and max (expected estimate uses min, worst case uses max). Inpatient (b1a, hospital tier 1)
becomes per-day intervals per stay; a flat per-stay copay is stored as a day-1 interval; Medicare-defined cost
sharing gets a note and no intervals.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from selector.ingest.normalize import blank, money_to_cents, pct_str_to_pct, plan_key, src_ref
from selector.ingest.parsers import read_delimited

SOURCE = "S2"
KEY_COLS = ("pbp_a_hnumber", "pbp_a_plan_identifier", "segment_id")
PLAN_AREA_HEADER = (
    "pbp_a_hnumber", "pbp_a_plan_identifier", "segment_id", "pbp_a_ben_cov", "pbp_a_plan_type", "orgtype",
    "bid_id", "contract_id", "plan_id", "segment_id", "county_code", "pending_flag", "partial_flag",
    "contract_year", "eghp_flag", "county", "stcd",
)  # fmt: skip

SERVICES: dict[str, tuple[str, str, str, str, str]] = {
    # service: (file, copay_min, copay_max, coins_min, coins_max)
    "pcp": ("b7", "pbp_b7a_copay_amt_mc_min", "pbp_b7a_copay_amt_mc_max",
            "pbp_b7a_coins_pct_mc_min", "pbp_b7a_coins_pct_mc_max"),
    "specialist": ("b7", "pbp_b7d_copay_amt_mc_min", "pbp_b7d_copay_amt_mc_max",
                   "pbp_b7d_coins_pct_mc_min", "pbp_b7d_coins_pct_mc_max"),
    "er": ("b4", "pbp_b4a_copay_amt_mc_min", "pbp_b4a_copay_amt_mc_max",
           "pbp_b4a_coins_pct_mc_min", "pbp_b4a_coins_pct_mc_max"),
    "urgent_care": ("b4", "pbp_b4b_copay_amt_mc_min", "pbp_b4b_copay_amt_mc_max",
                    "pbp_b4b_coins_pct_mc_min", "pbp_b4b_coins_pct_mc_max"),
    "outpatient": ("b9", "pbp_b9a_copay_ohs_amt_min", "pbp_b9a_copay_ohs_amt_max",
                            "pbp_b9a_coins_ohs_pct_min", "pbp_b9a_coins_ohs_pct_max"),
}  # fmt: skip
SECTION_FILES = {
    "b7": "pbp_b7_health_prof.txt",
    "b4": "pbp_b4_emerg_urgent.txt",
    "b9": "pbp_b9_outpat_hosp.txt",
}


def _key(r: dict[str, str]) -> str:
    return plan_key(r["pbp_a_hnumber"], r["pbp_a_plan_identifier"], r["segment_id"])


def parse_plan_area(text: str) -> Iterator[dict[str, str]]:
    """plan_key × SSA county code."""
    for r in read_delimited(text, "\t", PLAN_AREA_HEADER):
        code = r["county_code"].strip()
        if code:
            yield {"plan_key": _key(r), "ssa_code": code}


def parse_section(text: str, section: str, vintage: str) -> Iterator[dict[str, Any]]:
    services = {s: f for s, f in SERVICES.items() if f[0] == section}
    expected = KEY_COLS + tuple(c for f in services.values() for c in f[1:])
    rows = read_delimited(text, "\t")
    for r in rows:
        missing = [c for c in expected if c not in r]
        if missing:
            from selector.ingest.parsers import HeaderMismatch

            raise HeaderMismatch(f"PBP {section} missing columns {missing}")
        key = _key(r)
        for service, (_, cmin, cmax, pmin, pmax) in services.items():
            vals = (r[cmin], r[cmax], r[pmin], r[pmax])
            if all(blank(v) for v in vals):
                continue
            yield {
                "plan_key": key,
                "service_code": service,
                "copay_cents": money_to_cents(r[cmin]),
                "copay_max_cents": money_to_cents(r[cmax]),
                "coins_pct": pct_str_to_pct(r[pmin]),
                "coins_max_pct": pct_str_to_pct(r[pmax]),
                "notes": None,
                "src_ref": src_ref(SOURCE, vintage, f"{section}:{key}:{service}"),
            }


def parse_inpatient(text: str, vintage: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yields ('interval', row) for pbp_inpatient_interval and ('note', row) for pbp_benefit notes."""
    for r in read_delimited(text, "\t"):
        key = _key(r)
        ref = src_ref(SOURCE, vintage, f"b1a:{key}:t1")
        copay_md = r.get("pbp_b1a_mc_copay_cstshr_yn_t1", "").strip() == "1"
        coins_md = r.get("pbp_b1a_mc_coins_cstshr_yn_t1", "").strip() == "1"
        intervals: list[dict[str, Any]] = []
        for i in (1, 2, 3):
            amt = r.get(f"pbp_b1a_copay_mcs_amt_int{i}_t1", "")
            if not blank(amt):
                intervals.append({
                    "begin_day": int(r[f"pbp_b1a_copay_mcs_bgnd_int{i}_t1"]),
                    "end_day": int(r[f"pbp_b1a_copay_mcs_endd_int{i}_t1"]),
                    "copay_per_day_cents": money_to_cents(amt),
                    "coins_pct": None,
                })  # fmt: skip
            pct = r.get(f"pbp_b1a_coins_mcs_pct_int{i}_t1", "")
            if not blank(pct):
                intervals.append({
                    "begin_day": int(r[f"pbp_b1a_coins_mcs_bgnd_int{i}_t1"]),
                    "end_day": int(r[f"pbp_b1a_coins_mcs_endd_int{i}_t1"]),
                    "copay_per_day_cents": None,
                    "coins_pct": pct_str_to_pct(pct),
                })  # fmt: skip
        per_stay = r.get("pbp_b1a_copay_mcs_amt_t1", "")
        if not intervals and not blank(per_stay):
            intervals.append({"begin_day": 1, "end_day": 1, "copay_per_day_cents": money_to_cents(per_stay),
                              "coins_pct": None})  # fmt: skip
        for seq, iv in enumerate(sorted(intervals, key=lambda x: x["begin_day"]), start=1):
            yield "interval", {"plan_key": key, "seq": seq, **iv, "src_ref": ref}
        if copay_md or coins_md:
            note = "Original Medicare (Part A) inpatient cost sharing"
        elif intervals:
            note = "; ".join(
                f"days {iv['begin_day']}-{iv['end_day']}: "
                + (f"${iv['copay_per_day_cents'] / 100:,.2f}/day" if iv["copay_per_day_cents"] is not None
                   else f"{iv['coins_pct']}%")
                for iv in sorted(intervals, key=lambda x: x["begin_day"])
            )  # fmt: skip
        else:
            continue
        yield "note", {
            "plan_key": key, "service_code": "inpatient", "copay_cents": None, "copay_max_cents": None,
            "coins_pct": None, "coins_max_pct": None, "notes": note[:512], "src_ref": ref,
        }  # fmt: skip
