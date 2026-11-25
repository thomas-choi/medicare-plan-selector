"""`selector ingest --year YYYY`: fetch → lock check → parse/normalize → load (batched transactions) → validate."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Engine

from selector.ingest.fetch import Fetched, fetch_source
from selector.ingest.load import build_year, load_year, record_runs, unpublish_year
from selector.ingest.manifest import check_lock
from selector.ingest.parsers import county_xwalk, decode
from selector.ingest.validate import ValidationFailed, validate_year

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class IngestResult:
    year: int
    counts: dict[str, int]
    lock_changed: bool


def load_spec(sources_dir: Path, year: int) -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load((sources_dir / f"{year}.yaml").read_text())
    if int(spec["plan_year"]) != year:
        raise ValueError(f"{year}.yaml declares plan_year {spec['plan_year']}")
    return spec


def check_overrides_against_census(overrides_csv: Path, census: Path) -> list[str]:
    """Every override FIPS must exist in the Census county list (approved 'Census check').

    A blank FIPS marks a retired SSA area (DESIGN v0.5 B6); it must not be in use today, so it needs a reason and a
    citation instead.
    """
    known = set()
    for line in decode(census.read_bytes()).splitlines()[1:]:
        parts = line.split("|")
        if len(parts) > 2:
            known.add(parts[1] + parts[2])
    ov = county_xwalk.parse_overrides(overrides_csv.read_text())
    problems = [
        f"override {s}: FIPS {r['fips']} not in Census list"
        for s, r in ov.items()
        if r["fips"].strip() and r["fips"].strip() not in known
    ]
    problems += [
        f"override {s}: retired SSA area (blank FIPS) needs a reason and a citation"
        for s, r in ov.items()
        if not r["fips"].strip() and not (r["reason"].strip() and r["citation"].strip())
    ]
    return problems


def run_ingest(
    engine: Engine,
    year: int,
    *,
    sources_dir: Path = REPO_ROOT / "sources",
    raw_dir: Path | None = None,
    lock_path: Path = REPO_ROOT / "sources.lock",
    accept_new: bool = False,
    full: bool = False,
    offline: bool = False,
    fetched: dict[str, Fetched] | None = None,
) -> IngestResult:
    spec = load_spec(sources_dir, year)
    raw_dir = raw_dir or REPO_ROOT / "data" / "raw" / str(year)
    if fetched is None:
        fetched = {sid: fetch_source(sid, s, raw_dir, offline=offline) for sid, s in spec["sources"].items()}
    lock_changed = check_lock(lock_path, year, {sid: f.entry for sid, f in fetched.items()}, accept_new)

    overrides_csv = sources_dir / "ssa_fips_overrides.csv"
    if "XW2" in fetched:
        problems = check_overrides_against_census(overrides_csv, fetched["XW2"].paths["file"])
        if problems:
            raise ValidationFailed(problems)

    data = build_year(year, fetched, spec, overrides_csv)
    counts = load_year(engine, data, full=full)
    with engine.connect() as conn:
        problems = validate_year(conn, year, spec, data.oop_thresholds)
    if problems:
        unpublish_year(engine, year)  # the year stays not ready until an ingest passes
        raise ValidationFailed(problems)
    with engine.begin() as conn:
        record_runs(conn, year, fetched, counts, "ok")
    log.info("ingest %s ok: %s", year, counts)
    return IngestResult(year, counts, lock_changed)
