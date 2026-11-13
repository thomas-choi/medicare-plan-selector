"""RangeFile against an in-memory HTTP server (respx) that honours Range requests."""

from __future__ import annotations

import io
import os
import re
import zipfile

import httpx
import pytest
import respx

from selector.ingest import remote_zip
from selector.ingest.remote_zip import RangeNotSupported, open_remote_zip

URL = "https://example.test/big.zip"


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("dir/small.txt", "hello|world\n")
        z.writestr("dir/big.bin", os.urandom(3 * 1024 * 1024))
        z.writestr("dir/last.csv", "a,b\n1,2\n")
    return buf.getvalue()


def _serve(payload: bytes, ranges: bool = True) -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)

    def head(_: httpx.Request) -> httpx.Response:
        h = {"content-length": str(len(payload))}
        if ranges:
            h["accept-ranges"] = "bytes"
        return httpx.Response(200, headers=h)

    def get(req: httpx.Request) -> httpx.Response:
        m = re.fullmatch(r"bytes=(\d+)-(\d+)", req.headers.get("range", ""))
        if not m or not ranges:
            return httpx.Response(200, content=payload)
        a, b = int(m.group(1)), int(m.group(2))
        return httpx.Response(206, content=payload[a : b + 1])

    router.head(URL).mock(side_effect=head)
    router.get(URL).mock(side_effect=get)
    return router


def test_lists_and_reads_members_without_full_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote_zip, "BLOCK", 64 * 1024)
    payload = _make_zip()
    with _serve(payload):
        z = open_remote_zip(URL, httpx.Client())
        assert z.namelist() == ["dir/small.txt", "dir/big.bin", "dir/last.csv"]
        assert z.read("dir/last.csv") == b"a,b\n1,2\n"
        assert z.read("dir/small.txt") == b"hello|world\n"
        fetched = z.fp.requests * remote_zip.BLOCK  # type: ignore[union-attr]
        assert fetched < len(payload) / 2  # did not pull the 3 MiB member


def test_requires_range_support() -> None:
    with _serve(_make_zip(), ranges=False), pytest.raises(RangeNotSupported):
        open_remote_zip(URL, httpx.Client())
