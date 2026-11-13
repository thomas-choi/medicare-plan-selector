"""Manifest of fetched files and the committed `sources.lock` (sha256 pins per source and member)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class SourceEntry:
    url: str
    vintage: str
    sha256: str | None  # whole file; None when only members were range-read
    size: int
    last_modified: str = ""
    members: dict[str, str] = field(default_factory=dict)  # member name → sha256


class LockMismatch(RuntimeError):
    """A source differs from `sources.lock`. Re-run with --accept-new after reviewing the diff."""

    def __init__(self, diffs: list[str]) -> None:
        super().__init__("sources differ from sources.lock:\n  " + "\n  ".join(diffs))
        self.diffs = diffs


def _diff(sid: str, old: dict[str, Any], new: SourceEntry) -> list[str]:
    out: list[str] = []
    if old.get("url") != new.url:
        out.append(f"{sid}: url {old.get('url')} -> {new.url}")
    if new.sha256 is not None and old.get("sha256") != new.sha256:
        out.append(f"{sid}: sha256 {old.get('sha256')} -> {new.sha256}")
    for m, h in new.members.items():
        if old.get("members", {}).get(m) != h:
            out.append(f"{sid}: member {m!r} sha256 {old.get('members', {}).get(m)} -> {h}")
    return out


def check_lock(lock_path: Path, year: int, entries: dict[str, SourceEntry], accept_new: bool) -> bool:
    """Compare with the lock; write it when new or accepted. Returns True if the lock file changed."""
    lock: dict[str, Any] = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    year_lock: dict[str, Any] = lock.get(str(year), {})
    diffs = [d for sid, e in entries.items() if sid in year_lock for d in _diff(sid, year_lock[sid], e)]
    if diffs and not accept_new:
        raise LockMismatch(diffs)
    new_year = dict(year_lock)
    for sid, e in entries.items():
        rec = asdict(e)
        old = year_lock.get(sid, {})
        # Offline re-runs don't know HTTP metadata; keep what the online fetch recorded.
        for k in ("last_modified", "size"):
            if not rec[k] and old.get(k):
                rec[k] = old[k]
        new_year[sid] = rec
    if new_year == year_lock:
        return False
    lock[str(year)] = dict(sorted(new_year.items()))
    lock_path.write_text(json.dumps(dict(sorted(lock.items())), indent=2) + "\n")
    return True
