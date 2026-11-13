from __future__ import annotations

import json
from pathlib import Path

import pytest

from selector.ingest.manifest import LockMismatch, SourceEntry, check_lock


def _e(sha: str, member: str = "m1", lm: str = "Tue", size: int = 10) -> SourceEntry:
    return SourceEntry(
        url="https://x/a.zip", vintage="v", sha256=sha, size=size, last_modified=lm, members={"f": member}
    )


def test_new_lock_is_written(tmp_path: Path) -> None:
    lock = tmp_path / "sources.lock"
    assert check_lock(lock, 2027, {"S1": _e("aa")}, accept_new=False)
    assert json.loads(lock.read_text())["2027"]["S1"]["sha256"] == "aa"
    assert not check_lock(lock, 2027, {"S1": _e("aa")}, accept_new=False)  # unchanged


def test_mismatch_stops_without_accept_new(tmp_path: Path) -> None:
    lock = tmp_path / "sources.lock"
    check_lock(lock, 2027, {"S1": _e("aa")}, accept_new=False)
    with pytest.raises(LockMismatch) as ei:
        check_lock(lock, 2027, {"S1": _e("bb")}, accept_new=False)
    assert "sha256 aa -> bb" in str(ei.value)
    with pytest.raises(LockMismatch):
        check_lock(lock, 2027, {"S1": _e("aa", member="m2")}, accept_new=False)
    assert check_lock(lock, 2027, {"S1": _e("bb")}, accept_new=True)
    assert json.loads(lock.read_text())["2027"]["S1"]["sha256"] == "bb"


def test_offline_rerun_keeps_http_metadata(tmp_path: Path) -> None:
    lock = tmp_path / "sources.lock"
    check_lock(lock, 2027, {"S1": _e("aa")}, accept_new=False)
    assert not check_lock(lock, 2027, {"S1": _e("aa", lm="", size=0)}, accept_new=False)
    assert json.loads(lock.read_text())["2027"]["S1"]["last_modified"] == "Tue"


def test_years_are_independent(tmp_path: Path) -> None:
    lock = tmp_path / "sources.lock"
    check_lock(lock, 2027, {"S1": _e("aa")}, accept_new=False)
    check_lock(lock, 2028, {"S1": _e("zz")}, accept_new=False)
    data = json.loads(lock.read_text())
    assert data["2027"]["S1"]["sha256"] == "aa" and data["2028"]["S1"]["sha256"] == "zz"
