#!/usr/bin/env python3
"""pre-commit hook: refuse raw data, databases, archives and env files (DESIGN §11).

Usage: check_forbidden_files.py FILE...   (exit 1 and list offenders if any file is forbidden)
"""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

FORBIDDEN_SUFFIXES = (".zip", ".sqlite", ".sqlite3", ".db", ".rdb", ".aof", ".pem", ".key")
FORBIDDEN_DIRS = ("data",)
ALLOWED_ENV = {".env.example"}


def is_forbidden(path: str) -> bool:
    p = PurePosixPath(path.replace("\\", "/"))
    if p.parts and p.parts[0] in FORBIDDEN_DIRS:
        return True
    name = p.name
    if name.startswith(".env") and name not in ALLOWED_ENV:
        return True
    return name.lower().endswith(FORBIDDEN_SUFFIXES)


def main(argv: list[str]) -> int:
    bad = [f for f in argv if is_forbidden(f)]
    for f in bad:
        print(f"forbidden file in commit: {f}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
