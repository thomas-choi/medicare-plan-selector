"""Read members of a large remote ZIP with HTTP range requests (CMS Part D files are > 2 GB).

`RangeFile` is a seekable, read-only file object backed by `Range:` GETs with a small block cache, so the stdlib
`zipfile` module can list the central directory and stream single members without downloading the whole archive.
"""

from __future__ import annotations

import io
import zipfile
from collections import OrderedDict

import httpx

BLOCK = 1 << 20  # 1 MiB
CACHE_BLOCKS = 64


class RangeNotSupported(RuntimeError):
    pass


class RangeFile(io.RawIOBase):
    def __init__(self, url: str, client: httpx.Client | None = None) -> None:
        self.url = url
        self._client = client or httpx.Client(follow_redirects=True, timeout=120)
        head = self._client.head(url)
        head.raise_for_status()
        if head.headers.get("accept-ranges", "").lower() != "bytes":
            raise RangeNotSupported(url)
        self.size = int(head.headers["content-length"])
        self.last_modified = head.headers.get("last-modified", "")
        self._pos = 0
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self.requests = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self.size + offset
        else:
            raise ValueError(whence)
        self._pos = max(0, min(self._pos, self.size))
        return self._pos

    def _block(self, idx: int) -> bytes:
        if idx in self._cache:
            self._cache.move_to_end(idx)
            return self._cache[idx]
        start = idx * BLOCK
        end = min(start + BLOCK, self.size) - 1
        r = self._client.get(self.url, headers={"Range": f"bytes={start}-{end}"})
        self.requests += 1
        if r.status_code != 206:
            raise RangeNotSupported(f"{self.url}: status {r.status_code}")
        data = r.content
        self._cache[idx] = data
        if len(self._cache) > CACHE_BLOCKS:
            self._cache.popitem(last=False)
        return data

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self._pos
        out = bytearray()
        while size > 0 and self._pos < self.size:
            idx, off = divmod(self._pos, BLOCK)
            chunk = self._block(idx)[off : off + size]
            out += chunk
            self._pos += len(chunk)
            size -= len(chunk)
        return bytes(out)

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def open_remote_zip(url: str, client: httpx.Client | None = None) -> zipfile.ZipFile:
    return zipfile.ZipFile(RangeFile(url, client))
