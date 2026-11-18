"""HUD fallback: load a quarterly USPS ZIP-COUNTY crosswalk file instead of calling the API.

HUD-API-SETUP.md "Fallback if the token isn't available": download the ZIP-COUNTY file for the latest quarter from
https://www.huduser.gov/portal/datasets/usps_crosswalk.html (e.g. `ZIP_COUNTY_062026.xlsx`) and run
`selector hud load-file <path>`. CSV (same columns) also works. Columns used: ZIP, COUNTY (5-digit FIPS), RES_RATIO.
Only ZIP→county rows are stored (`zip_county_cache`), never anything about a user.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path

from selector.geo.hud import ZipCounty

FILENAME_RE = re.compile(r"(\d{2})(\d{4})")  # ZIP_COUNTY_MMYYYY
REQUIRED = ("ZIP", "COUNTY", "RES_RATIO")


class HudFileError(ValueError):
    pass


def year_quarter_from_name(path: Path) -> tuple[int, int] | None:
    m = FILENAME_RE.search(path.stem)
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return year, (month - 1) // 3 + 1


def _rows_from_csv(text: str) -> Iterator[dict[str, str]]:
    yield from csv.DictReader(io.StringIO(text))


def _rows_from_xlsx(path: Path) -> Iterator[dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = [str(h or "").strip().upper() for h in next(it)]
    for row in it:
        yield {header[i]: "" if v is None else str(v) for i, v in enumerate(row) if i < len(header)}
    wb.close()


def _normalize(rows: Iterable[dict[str, str]], year: int, quarter: int) -> list[ZipCounty]:
    out: list[ZipCounty] = []
    for i, raw in enumerate(rows):
        r = {k.strip().upper(): (v or "").strip() for k, v in raw.items() if k}
        if i == 0:
            missing = [c for c in REQUIRED if c not in r]
            if missing:
                raise HudFileError(f"HUD file is missing columns {missing}; expected {list(REQUIRED)}")
        z, county = r["ZIP"].split(".")[0].zfill(5), r["COUNTY"].split(".")[0].zfill(5)
        if not (z.isdigit() and len(z) == 5 and county.isdigit() and len(county) == 5):
            raise HudFileError(f"row {i + 2}: bad ZIP/COUNTY {r['ZIP']!r}/{r['COUNTY']!r}")
        try:
            ratio = Decimal(r["RES_RATIO"] or "0")
        except InvalidOperation as e:
            raise HudFileError(f"row {i + 2}: bad RES_RATIO {r['RES_RATIO']!r}") from e
        out.append(ZipCounty(z, county, ratio, year, quarter))
    return out


def read_hud_file(path: Path, year: int | None = None, quarter: int | None = None) -> list[ZipCounty]:
    yq = (year, quarter) if year and quarter else year_quarter_from_name(path)
    if not yq:
        raise HudFileError("cannot tell the HUD year/quarter from the file name; pass --year and --quarter")
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return _normalize(_rows_from_xlsx(path), *yq)
    return _normalize(_rows_from_csv(path.read_text(encoding="utf-8-sig")), *yq)


STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
    "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "AS": "60", "GU": "66", "MP": "69",
    "PR": "72", "VI": "78",
}  # fmt: skip


def state_filter(rows: list[ZipCounty], state: str) -> list[ZipCounty]:
    prefix = STATE_FIPS.get(state.upper())
    if prefix is None:
        raise HudFileError(f"unknown state {state!r}")
    return [r for r in rows if r.fips.startswith(prefix)]
