"""Regression tests for the developer tooling QA found (qa/QA-REPORT.md)."""

from __future__ import annotations

import re

from selector.config import REPO_ROOT

MAKEFILE = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def _recipe(target: str) -> tuple[str, list[str]]:
    """(prerequisite line, recipe lines) of a Makefile target."""
    m = re.search(rf"^{re.escape(target)}:(.*)$\n((?:\t.*\n?)*)", MAKEFILE, re.M)
    assert m, f"no target {target}"
    return m.group(1), m.group(2).splitlines()


def test_make_never_runs_npx() -> None:
    """QA #3: `npx tsc` without node_modules downloads an unrelated npm package called `tsc`."""
    recipes = [line for line in MAKEFILE.splitlines() if line.startswith("\t")]
    assert not [line for line in recipes if re.search(r"\bnpx\b", line)]


def test_frontend_targets_check_dependencies_first() -> None:
    for target in ("lint", "test-fast", "test-frontend"):
        prereqs, _ = _recipe(target)
        assert "frontend-deps" in prereqs.split("##")[0], target
    _, body = _recipe("frontend-deps")
    assert "npm ci" in "\n".join(body)
