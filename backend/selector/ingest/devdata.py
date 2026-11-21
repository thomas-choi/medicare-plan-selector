"""Development data: the committed ≤200-row CMS fixtures as an offline ingest source (`make ingest-dev`).

The fixtures are public CMS sample rows (see backend/tests/fixtures/cms/2027/MANIFEST.json and DATA-SOURCES.md).
They are enough to exercise the whole app for Maricopa County, AZ (golden plan H0028_028_0) without downloading
the full CMS files.
"""

from __future__ import annotations

from pathlib import Path

from selector.ingest.fetch import Fetched
from selector.ingest.manifest import SourceEntry, sha256_file

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = BACKEND_DIR / "tests" / "fixtures" / "cms"
DEV_ZIP_FILE = BACKEND_DIR / "tests" / "fixtures" / "hud" / "zip_county_dev.csv"

LAYOUT = {
    "S1": {"landscape": "landscape.csv"},
    "S2": {"plan_area": "plan_area.txt", "b7": "b7.txt", "b4": "b4.txt", "b9": "b9.txt", "b1a": "b1a.txt",
           "b16": "b16.txt"},
    "S3": {"geo": "geo.txt", "plan_info": "plan_info.txt", "formulary": "formulary.txt", "cost": "cost.txt",
           "insulin": "insulin.txt"},
    "XW1": {"penetration": "penetration.csv"},
    "XW2": {"file": "census_county.txt"},
}  # fmt: skip
VINTAGE = {"S1": "202611", "S2": "2027-pbp-20261001", "S3": "20261031", "XW1": "2026-11", "XW2": "2020"}


def fixture_fetched(root: Path) -> dict[str, Fetched]:
    """`Fetched` bundles for every source, read from a fixture directory (no network)."""
    out: dict[str, Fetched] = {}
    for sid, members in LAYOUT.items():
        paths = {alias: root / name for alias, name in members.items()}
        missing = [str(p) for p in paths.values() if not p.exists()]
        if missing:
            raise FileNotFoundError(f"fixture files missing: {missing}")
        entry = SourceEntry(url=f"fixture://{sid}", vintage=VINTAGE[sid], sha256=None, size=0)
        entry.members = {p.name: sha256_file(p) for p in paths.values()}
        out[sid] = Fetched(entry, paths)
    return out
