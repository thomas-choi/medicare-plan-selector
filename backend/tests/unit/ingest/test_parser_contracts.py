"""Parser contract tests: the fixture headers (copied from the real 2027 files) match what parsers expect."""

from __future__ import annotations

import pytest

from selector.ingest.parsers import HeaderMismatch, county_xwalk, decode, landscape, pbp, read_delimited, spuf
from tests.cms_fixtures import FIX


def _header(name: str, delim: str) -> list[str]:
    return decode((FIX / name).read_bytes()).splitlines()[0].split(delim)


@pytest.mark.parametrize(
    ("name", "delim", "expected", "exact"),
    [
        ("landscape.csv", ",", landscape.EXPECTED_HEADER, True),
        ("geo.txt", "|", spuf.GEO_HEADER, True),
        ("plan_info.txt", "|", spuf.PLAN_INFO_HEADER, True),
        ("formulary.txt", "|", spuf.FORMULARY_HEADER, True),
        ("cost.txt", "|", spuf.COST_HEADER, True),
        ("insulin.txt", "|", spuf.INSULIN_HEADER, True),
        ("plan_area.txt", "\t", pbp.PLAN_AREA_HEADER, True),
        ("penetration.csv", ",", county_xwalk.EXPECTED_HEADER, False),
    ],
)
def test_header_contract(name: str, delim: str, expected: tuple[str, ...], exact: bool) -> None:
    got = [h.strip() for h in _header(name, delim)]
    if exact:
        assert got == list(expected)
    else:
        assert got[: len(expected)] == list(expected)


def test_pbp_sections_have_mapped_columns() -> None:
    for section, fname in (("b7", "b7.txt"), ("b4", "b4.txt"), ("b9", "b9.txt")):
        cols = set(_header(fname, "\t"))
        for service, spec in pbp.SERVICES.items():
            if spec[0] == section:
                assert set(spec[1:]) <= cols, service


def test_header_drift_is_refused() -> None:
    with pytest.raises(HeaderMismatch):
        list(read_delimited("Contract Year,Something Else\n2027,x\n", ",", landscape.EXPECTED_HEADER))
