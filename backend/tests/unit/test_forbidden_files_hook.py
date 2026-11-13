from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_forbidden_files.py"
_spec = importlib.util.spec_from_file_location("check_forbidden_files", _SCRIPT)
assert _spec and _spec.loader
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "backend/.env",
        "deploy/.env.prod",
        "data/raw/2027/landscape.csv",
        "cy2027-landscape-202611.zip",
        "backend/local.sqlite",
        "dump.rdb",
        "certs/server.key",
    ],
)
def test_blocks(path: str) -> None:
    assert hook.is_forbidden(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "backend/tests/fixtures/cms/2027/landscape_sample.csv",
        "docs/DATA-SOURCES.md",
        "backend/selector/ingest/remote_zip.py",
        "frontend/src/data/labels.ts",
    ],
)
def test_allows(path: str) -> None:
    assert not hook.is_forbidden(path)


def test_main_exit_code() -> None:
    assert hook.main([".env.example", "README.md"]) == 0
    assert hook.main(["README.md", ".env"]) == 1
