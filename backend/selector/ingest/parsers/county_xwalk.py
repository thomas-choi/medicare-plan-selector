"""SSA → FIPS county crosswalk.

Order (first match wins; DESIGN v0.5 B6):
1. the committed, cited `sources/ssa_fips_overrides.csv` (`override`; a row with a blank FIPS marks a **retired**
   SSA area that has no FIPS county today, e.g. Alaska's Valdez-Cordova, status `retired`);
2. CMS "MA State/County Penetration" file, source XW1 (`crosswalk`);
3. NBER "SSA to FIPS State and County Crosswalk", source XW3, only for SSA codes missing from XW1 (`crosswalk_nber`;
   XW1 has no Alaska or Connecticut rows);
4. otherwise `pending` (ingest validation fails unless the state is in `pending_fips_states`).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from typing import Any

from selector.ingest.normalize import src_ref
from selector.ingest.parsers import read_delimited

SOURCE = "XW1"
NBER_REQUIRED = ("ssa_code", "fipscounty")  # other NBER columns (CBSA year, names) change from year to year
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


def parse_nber(text: str) -> dict[str, str]:
    """SSA → FIPS from the NBER crosswalk CSV. Rows without both codes (e.g. CT planning regions) are skipped."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    header = tuple(h.strip() for h in reader.fieldnames or ())
    missing = [c for c in NBER_REQUIRED if c not in header]
    if missing:
        raise ValueError(f"XW3: columns {missing} missing from NBER crosswalk header {header}")
    out: dict[str, str] = {}
    for r in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        ssa, fips = row["ssa_code"], row["fipscounty"]
        if not (len(ssa) == 5 and len(fips) == 5 and ssa.isdigit() and fips.isdigit()):
            continue
        if out.setdefault(ssa, fips) != fips:
            raise ValueError(f"XW3: SSA {ssa} maps to two FIPS ({out[ssa]}, {fips})")
    return out


def parse_overrides(text: str) -> dict[str, dict[str, str]]:
    return {r["ssa_code"]: r for r in read_delimited(text, ",", OVERRIDE_HEADER)}


def build_counties(
    geo_rows: Iterable[dict[str, str]],
    xwalk: dict[str, str],
    overrides: dict[str, dict[str, str]],
    vintage: str,
    nber: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Merge the S3 geographic locator with the crosswalks; every SSA code gets a status."""
    nber = nber or {}
    for g in geo_rows:
        ssa = g["COUNTY_CODE"].strip()
        ov = overrides.get(ssa)
        if ov is not None and ov["fips"].strip():
            fips, status, partial = ov["fips"].strip(), "override", ov["partial"].strip().upper() == "Y"
        elif ov is not None:
            fips, status, partial = None, "retired", False
        elif ssa in xwalk:
            fips, status, partial = xwalk[ssa], "crosswalk", False
        elif ssa in nber:
            fips, status, partial = nber[ssa], "crosswalk_nber", False
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
