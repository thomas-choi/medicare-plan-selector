"""Pure parsers: text in, row dicts out. Each checks its header exactly (parser contract tests)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Sequence


class HeaderMismatch(ValueError):
    """The file's header differs from the design — stop and ask (handoff §2)."""


def read_delimited(text: str, delimiter: str, expected: Sequence[str] | None = None) -> Iterator[dict[str, str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [h.strip() for h in next(reader)]
    if expected is not None and list(expected) != header[: len(expected)]:
        missing = [h for h in expected if h not in header]
        raise HeaderMismatch(f"header differs; missing={missing} got={header}")
    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue
        yield dict(zip(header, row, strict=False))


def decode(raw: bytes) -> str:
    """CMS files are UTF-8 (with BOM) or cp1252."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")
