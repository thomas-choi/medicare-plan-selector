"""S3 CMS monthly Part D files (pipe-delimited). Field codes per CMS PUF record layout 2026 (same headers in 2027):

- COVERAGE_LEVEL: 0=pre-deductible, 1=initial coverage, 3=catastrophic
- DAYS_SUPPLY: 1=30 days, 2=90 days, 3=other, 4=60 days
- COST_TYPE_*: 0=not offered, 1=copay (dollars), 2=coinsurance (fraction, .25 = 25%)
- Insulin cost = lesser of the copay and the coinsurance amount (Methodology SPUF 2026).
- COUNTY_CODE is the 5-character SSA state/county code.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from selector.ingest.normalize import blank, fraction_to_pct, money_to_cents, plan_key, src_ref, yn
from selector.ingest.parsers import read_delimited

SOURCE = "S3"

GEO_HEADER = (
    "COUNTY_CODE",
    "STATENAME",
    "COUNTY",
    "MA_REGION_CODE",
    "MA_REGION",
    "PDP_REGION_CODE",
    "PDP_REGION",
)
PLAN_INFO_HEADER = (
    "CONTRACT_ID", "PLAN_ID", "SEGMENT_ID", "CONTRACT_NAME", "PLAN_NAME", "FORMULARY_ID", "PREMIUM",
    "DEDUCTIBLE", "MA_REGION_CODE", "PDP_REGION_CODE", "STATE", "COUNTY_CODE", "SNP", "PLAN_SUPPRESSED_YN",
)  # fmt: skip
FORMULARY_HEADER = (
    "FORMULARY_ID", "FORMULARY_VERSION", "CONTRACT_YEAR", "RXCUI", "NDC", "TIER_LEVEL_VALUE",
    "QUANTITY_LIMIT_YN", "QUANTITY_LIMIT_AMOUNT", "QUANTITY_LIMIT_DAYS", "PRIOR_AUTHORIZATION_YN",
    "STEP_THERAPY_YN", "SELECTED_DRUG_YN",
)  # fmt: skip
PHARMACY_TYPES = ("PREF", "NONPREF", "MAIL_PREF", "MAIL_NONPREF")
PHARMACY_NAME = {"PREF": "pref_retail", "NONPREF": "retail", "MAIL_PREF": "pref_mail", "MAIL_NONPREF": "mail"}
COST_HEADER = (
    "CONTRACT_ID", "PLAN_ID", "SEGMENT_ID", "COVERAGE_LEVEL", "TIER", "DAYS_SUPPLY",
    *[f"COST_{f}_{p}" for p in PHARMACY_TYPES for f in ("TYPE", "AMT", "MIN_AMT", "MAX_AMT")],
    "TIER_SPECIALTY_YN", "DED_APPLIES_YN",
)  # fmt: skip
INSULIN_HEADER = (
    "CONTRACT_ID", "PLAN_ID", "SEGMENT_ID", "TIER", "DAYS_SUPPLY",
    "copay_amt_pref_insln", "copay_amt_nonpref_insln", "copay_amt_mail_pref_insln", "copay_amt_mail_nonpref_insln",
    "coin_amt_pref_insln", "coin_amt_nonpref_insln", "coin_amt_mail_pref_insln", "coin_amt_mail_nonpref_insln",
)  # fmt: skip

PHASE = {"0": "deductible", "1": "initial", "3": "catastrophic"}
DAYS = {"1": 30, "2": 90, "3": 0, "4": 60}


class UnknownCode(ValueError):
    """A coded value outside the record layout — stop and ask."""


def parse_geo(text: str) -> Iterator[dict[str, str]]:
    yield from read_delimited(text, "|", GEO_HEADER)


def parse_plan_info(text: str) -> Iterator[dict[str, Any]]:
    """One row per plan × county (MA) or plan × region (PDP).

    Suppressed plans (PLAN_SUPPRESSED_YN=Y) appear in no other Part D file (CMS methodology); they are yielded
    with `suppressed=True` and no formulary so the loader can flag them.
    """
    for r in read_delimited(text, "|", PLAN_INFO_HEADER):
        yield {
            "suppressed": yn(r["PLAN_SUPPRESSED_YN"]),
            "plan_key": plan_key(r["CONTRACT_ID"], r["PLAN_ID"], r["SEGMENT_ID"]),
            "formulary_id": r["FORMULARY_ID"].strip(),
            "county_code": r["COUNTY_CODE"].strip() or None,
            "pdp_region_code": r["PDP_REGION_CODE"].strip() or None,
            "deductible_cents": money_to_cents(r["DEDUCTIBLE"]),
        }


def parse_formulary(text: str, vintage: str) -> Iterator[dict[str, Any]]:
    for r in read_delimited(text, "|", FORMULARY_HEADER):
        fid, ndc = r["FORMULARY_ID"].strip(), r["NDC"].strip()
        yield {
            "formulary_id": fid,
            "ndc": ndc,
            "rxcui": r["RXCUI"].strip() or None,
            "tier": int(r["TIER_LEVEL_VALUE"]),
            "prior_auth": yn(r["PRIOR_AUTHORIZATION_YN"]),
            "step": yn(r["STEP_THERAPY_YN"]),
            "qty_limit": yn(r["QUANTITY_LIMIT_YN"]),
            "qty_amount": None if blank(r["QUANTITY_LIMIT_AMOUNT"]) else r["QUANTITY_LIMIT_AMOUNT"].strip(),
            "qty_days": None if blank(r["QUANTITY_LIMIT_DAYS"]) else int(r["QUANTITY_LIMIT_DAYS"]),
            "src_ref": src_ref(SOURCE, vintage, f"formulary:{fid}:{ndc}"),
        }


def _code(table: dict[str, Any], v: str, field: str) -> Any:
    try:
        return table[v.strip()]
    except KeyError as e:
        raise UnknownCode(f"{field}={v!r}") from e


def parse_beneficiary_cost(text: str, vintage: str) -> Iterator[dict[str, Any]]:
    """One `tier_cost` row per plan × phase × tier × days supply × pharmacy type that is offered."""
    for r in read_delimited(text, "|", COST_HEADER):
        key = plan_key(r["CONTRACT_ID"], r["PLAN_ID"], r["SEGMENT_ID"])
        phase = _code(PHASE, r["COVERAGE_LEVEL"], "COVERAGE_LEVEL")
        days = _code(DAYS, r["DAYS_SUPPLY"], "DAYS_SUPPLY")
        tier = int(r["TIER"])
        for p in PHARMACY_TYPES:
            ctype = r[f"COST_TYPE_{p}"].strip()
            if ctype in ("", "0"):
                continue
            if ctype not in ("1", "2"):
                raise UnknownCode(f"COST_TYPE_{p}={ctype!r}")
            amt = r[f"COST_AMT_{p}"]
            yield {
                "plan_key": key,
                "tier": tier,
                "phase": phase,
                "pharmacy_type": PHARMACY_NAME[p],
                "days_supply": days,
                "copay_cents": money_to_cents(amt) if ctype == "1" else None,
                "coins_pct": fraction_to_pct(amt) if ctype == "2" else None,
                "coins_min_cents": money_to_cents(r[f"COST_MIN_AMT_{p}"]) if ctype == "2" else None,
                "coins_max_cents": money_to_cents(r[f"COST_MAX_AMT_{p}"]) if ctype == "2" else None,
                "ded_applies": yn(r["DED_APPLIES_YN"]),
                "specialty": yn(r["TIER_SPECIALTY_YN"]),
                "src_ref": src_ref(SOURCE, vintage, f"cost:{key}:{r['COVERAGE_LEVEL']}:{tier}:{r['DAYS_SUPPLY']}:{p}"),
            }


def parse_insulin(text: str, vintage: str) -> Iterator[dict[str, Any]]:
    cols = {"PREF": "pref", "NONPREF": "nonpref", "MAIL_PREF": "mail_pref", "MAIL_NONPREF": "mail_nonpref"}
    for r in read_delimited(text, "|", INSULIN_HEADER):
        key = plan_key(r["CONTRACT_ID"], r["PLAN_ID"], r["SEGMENT_ID"])
        days = _code(DAYS, r["DAYS_SUPPLY"], "DAYS_SUPPLY")
        tier = 0 if blank(r["TIER"]) else int(r["TIER"])  # missing for defined-standard plans
        for p, c in cols.items():
            copay = money_to_cents(r[f"copay_amt_{c}_insln"])
            coins = fraction_to_pct(r[f"coin_amt_{c}_insln"])
            if copay is None and coins is None:
                continue
            yield {
                "plan_key": key,
                "tier": tier,
                "pharmacy_type": PHARMACY_NAME[p],
                "days_supply": days,
                "copay_cents": copay,
                "coins_pct": coins,
                "src_ref": src_ref(SOURCE, vintage, f"insulin:{key}:{tier}:{r['DAYS_SUPPLY']}:{p}"),
            }
