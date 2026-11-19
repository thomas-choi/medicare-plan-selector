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


COMPOSE_DEV = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
COMPOSE_PROD = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")


def test_no_port_mapping_can_default_to_all_interfaces() -> None:
    """QA #5: `"${MSP_WEB_BIND:-}:8080:8080"` binds 0.0.0.0 when the variable is blank."""
    for text_ in (COMPOSE_DEV, COMPOSE_PROD):
        ports = re.findall(r'^\s*-\s*"([^"]*:\d+)"\s*$', text_, re.M)
        assert ports
        for p in ports:
            m = re.fullmatch(r"(\$\{[^}]*\}|[0-9.]*):(\$\{[^}]*\}|\d+):\d+", p)
            host = m.group(1) if m else ""
            assert host, f"port {p!r} has no host IP (binds 0.0.0.0)"
            assert not re.search(r"\$\{\w+(:?-)?\}", host), f"{p!r}: host IP without a safe default"
            default = re.fullmatch(r"\$\{\w+:-([0-9.]+)\}", host)
            assert host == "127.0.0.1" or (default and default.group(1) == "127.0.0.1"), p


def test_app_up_never_recreates_the_tmpfs_stack() -> None:
    """QA #6: `make app-up` recreated MySQL (tmpfs) and silently wiped the dev data."""
    prereqs, body = _recipe("app-up")
    assert "stack-up" in prereqs
    up = next(line for line in body if " up " in line)
    assert "--no-deps" in up and up.split("--no-deps", 1)[1].split("||")[0].split() == ["api", "web"]
    assert "make ingest-dev" in "\n".join(body)
    _, stack = _recipe("stack-up")
    assert "--no-recreate" in stack[0]


def test_api_healthchecks_use_readiness() -> None:
    for text_ in (COMPOSE_DEV, COMPOSE_PROD):
        assert "/api/ready" in text_ and "/api/health'" not in text_
