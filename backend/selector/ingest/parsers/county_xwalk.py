"""SSA → FIPS county crosswalk.

Primary: CMS "MA State/County Penetration" file (has both SSA and FIPS). Supplemented by the committed, cited
`sources/ssa_fips_overrides.csv`. Counties with neither (Alaska, Connecticut at MVP) get `fips_status='pending'`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from selector.ingest.normalize import src_ref
from selector.ingest.parsers import read_delimited

SOURCE = "XW1"
EXPECTED_HEADER = ("State Name", "County Name", "FIPSST", "FIPSCNTY", "FIPS", "SSAST", "SSACNTY", "SSA")
OVERRIDE_HEADER = ("ssa_code", "fips", "state", "county", "partial", "reason", "citation")


def parse_penetration(text: str) -> dict[str, str]:
    """SSA → FIPS. Only geographic columns are used; enrollment counts are ignored."""
    out: dict[str, str] = {}
    for r in read_delimited(text, ",", EXPECTED_HEADER):
        ssa, fips = r["SSA"].strip(), r["FIPS"].strip()
        if len(ssa) == 5 and len(fips) == 5:
            out.setdefault(ssa, fips)
    return out


def parse_overrides(text: str) -> dict[str, dict[str, str]]:
    return {r["ssa_code"]: r for r in read_delimited(text, ",", OVERRIDE_HEADER)}


def build_counties(
    geo_rows: Iterable[dict[str, str]],
    xwalk: dict[str, str],
    overrides: dict[str, dict[str, str]],
    vintage: str,
) -> Iterator[dict[str, Any]]:
    """Merge the S3 geographic locator with the crosswalk; every SSA code gets a status."""
    for g in geo_rows:
        ssa = g["COUNTY_CODE"].strip()
        ov = overrides.get(ssa)
        if ov is not None and ov["fips"].strip():
            fips, status, partial = ov["fips"].strip(), "override", ov["partial"].strip().upper() == "Y"
        elif ssa in xwalk:
            fips, status, partial = xwalk[ssa], "crosswalk", False
        else:
            fips, status, partial = None, "pending", False
        if "(partial)" in g["COUNTY"].lower():
            partial = True
        yield {
            "ssa_code": ssa,
            "fips": fips,
            "state": None,
            "state_name": g["STATENAME"].strip(),
            "name": g["COUNTY"].strip(),
            "ma_region_code": g["MA_REGION_CODE"].strip() or None,
            "pdp_region_code": g["PDP_REGION_CODE"].strip() or None,
            "fips_status": status,
            "partial": partial,
            "src_ref": src_ref("S3", vintage, f"geo:{ssa}", fips_source=status),
        }
