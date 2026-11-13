"""Build `Fetched` bundles from the committed ≤200-row CMS fixtures (no network)."""

from __future__ import annotations

from pathlib import Path

from selector.ingest.fetch import Fetched
from selector.ingest.manifest import SourceEntry, sha256_file

FIX = Path(__file__).resolve().parent / "fixtures" / "cms" / "2027"
REPO = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO / "sources"

LAYOUT = {
    "S1": {"landscape": "landscape.csv"},
    "S2": {"plan_area": "plan_area.txt", "b7": "b7.txt", "b4": "b4.txt", "b9": "b9.txt", "b1a": "b1a.txt"},
    "S3": {"geo": "geo.txt", "plan_info": "plan_info.txt", "formulary": "formulary.txt", "cost": "cost.txt",
           "insulin": "insulin.txt"},
    "XW1": {"penetration": "penetration.csv"},
    "XW2": {"file": "census_county.txt"},
}  # fmt: skip
VINTAGE = {"S1": "202611", "S2": "2027-pbp-20261001", "S3": "20261031", "XW1": "2026-11", "XW2": "2020"}


def fixture_fetched(root: Path = FIX) -> dict[str, Fetched]:
    out: dict[str, Fetched] = {}
    for sid, members in LAYOUT.items():
        paths = {alias: root / name for alias, name in members.items()}
        entry = SourceEntry(url=f"fixture://{sid}", vintage=VINTAGE[sid], sha256=None, size=0)
        entry.members = {p.name: sha256_file(p) for p in paths.values()}
        out[sid] = Fetched(entry, paths)
    return out
