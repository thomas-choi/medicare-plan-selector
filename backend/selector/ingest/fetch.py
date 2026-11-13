"""Download sources into the git-ignored raw directory and extract the members the parsers need."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from selector.ingest.manifest import SourceEntry, sha256_bytes, sha256_file
from selector.ingest.remote_zip import open_remote_zip

USER_AGENT = "medicare-plan-selector-ingest (+https://github.com/thomas-choi/medicare-plan-selector)"


@dataclass
class Fetched:
    entry: SourceEntry
    paths: dict[str, Path]  # member alias → extracted file


def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=600, headers={"User-Agent": USER_AGENT})


def _download(url: str, dest: Path, client: httpx.Client) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        lm = r.headers.get("last-modified", "")
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest.stat().st_size, lm


def fetch_source(sid: str, spec: dict[str, Any], raw_dir: Path, offline: bool = False) -> Fetched:
    """Fetch one source. With `offline`, reuse files already in raw_dir (no network)."""
    url: str = spec["url"]
    kind: str = spec["fetch"]
    vintage = str(spec["vintage"])
    sdir = raw_dir / sid
    members: dict[str, str] = spec.get("members", {}) or {}
    paths: dict[str, Path] = {}
    client = _client()

    if kind in ("zip", "file"):
        dest = sdir / Path(url).name
        lm = ""
        if not (offline and dest.exists()):
            _, lm = _download(url, dest, client)
        entry = SourceEntry(url=url, vintage=vintage, sha256=sha256_file(dest), size=dest.stat().st_size,
                            last_modified=lm)  # fmt: skip
        if kind == "file":
            paths["file"] = dest
        else:
            with zipfile.ZipFile(dest) as z:
                for alias, name in members.items():
                    out = sdir / "members" / Path(name).name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    data = z.read(name)
                    out.write_bytes(data)
                    entry.members[name] = sha256_bytes(data)
                    paths[alias] = out
        return Fetched(entry, paths)

    if kind == "remote_nested_zip":
        mdir = sdir / "members"
        mdir.mkdir(parents=True, exist_ok=True)
        entry = SourceEntry(url=url, vintage=vintage, sha256=None, size=0)
        if offline:
            for alias, prefix in members.items():
                found = sorted(p for p in mdir.iterdir() if p.name.lower().startswith(prefix.lower())
                               and "sample" not in p.name.lower())  # fmt: skip
                if not found:
                    raise FileNotFoundError(f"{sid}: no offline member for {prefix!r} in {mdir}")
                paths[alias] = found[0]
                entry.members[found[0].name] = sha256_file(found[0])
            return Fetched(entry, paths)
        outer = open_remote_zip(url, client)
        entry.size = outer.fp.size  # type: ignore[union-attr]
        entry.last_modified = outer.fp.last_modified  # type: ignore[union-attr]
        for alias, prefix in members.items():
            inner_names = [n for n in outer.namelist() if n.lower().startswith(prefix.lower())]
            if len(inner_names) != 1:
                raise FileNotFoundError(f"{sid}: expected one inner zip for {prefix!r}, got {inner_names}")
            inner = zipfile.ZipFile(io.BytesIO(outer.read(inner_names[0])))
            txt = [n for n in inner.namelist() if n.lower().endswith(".txt") and "sample" not in n.lower()]
            if len(txt) != 1:
                raise FileNotFoundError(f"{sid}: expected one data file in {inner_names[0]}, got {txt}")
            data = inner.read(txt[0])
            out = mdir / Path(txt[0]).name
            out.write_bytes(data)
            entry.members[out.name] = sha256_bytes(data)
            paths[alias] = out
        return Fetched(entry, paths)

    raise ValueError(f"{sid}: unknown fetch kind {kind!r}")
