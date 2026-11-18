"""Build `Fetched` bundles from the committed ≤200-row CMS fixtures (no network)."""

from __future__ import annotations

from pathlib import Path

from selector.ingest import devdata
from selector.ingest.fetch import Fetched

FIX = devdata.FIXTURE_ROOT / "2027"
REPO = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO / "sources"
LAYOUT = devdata.LAYOUT
VINTAGE = devdata.VINTAGE


def fixture_fetched(root: Path = FIX) -> dict[str, Fetched]:
    return devdata.fixture_fetched(root)
