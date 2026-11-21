"""Regression tests for the developer tooling QA found (qa/QA-REPORT.md)."""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

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
    assert "local-stack-up" in "\n".join(stack)
    assert all("--no-recreate" in line for line in stack if " up " in line)
    _, local = _recipe("local-stack-up")
    assert "--no-recreate" in local[0]
    prereqs, _ = _recipe("test-backend")
    assert prereqs.split() == ["local-stack-up"]  # tests always use this machine's stack


DEVDB = REPO_ROOT / "scripts" / "devdb.sh"


def _devdb(env: dict[str, str]) -> dict[str, str]:
    """Source scripts/devdb.sh in a clean bash with `env` and return what it sets."""
    out = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "bash",
            "-c",
            f'. "{DEVDB}"; for v in DEV_DB_HOST DEV_DB_PORT DEV_REDIS_HOST DEV_REDIS_PORT DEV_DB_REMOTE '
            "DEV_REDIS_REMOTE; do "
            'printf "%s=%s\\n" "$v" "${!v}"; done; env | grep -E "^COMPOSE_" || true',
        ],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


def test_devdb_local_by_default() -> None:
    got = _devdb({})
    assert got["DEV_DB_HOST"] == "127.0.0.1" and got["DEV_DB_REMOTE"] == ""
    assert not any(k.startswith("COMPOSE_") for k in got)
    got = _devdb({"INGEST_DATABASE_URL": "mysql+pymysql://u:p@127.0.0.1:3307/msp"})
    assert got["DEV_DB_REMOTE"] == ""


def test_devdb_remote_stack_from_env_urls() -> None:
    """ml3090 coding host using the dev stack on ml3060 (192.0.2.16 stands in for its LAN address)."""
    db = "mysql+pymysql://msp_api:pw@192.0.2.16:3307/msp"
    got = _devdb(
        {
            "DATABASE_URL": db,
            "INGEST_DATABASE_URL": db.replace("msp_api", "msp_ingest"),
            "MIGRATOR_DATABASE_URL": db.replace("msp_api", "msp_migrator"),
            "REDIS_URL": "redis://:pw@192.0.2.16:6380/0",
        }
    )
    assert got["DEV_DB_REMOTE"] == "1"
    assert (got["DEV_DB_HOST"], got["DEV_DB_PORT"]) == ("192.0.2.16", "3307")
    assert (got["DEV_REDIS_HOST"], got["DEV_REDIS_PORT"]) == ("192.0.2.16", "6380")
    assert got["COMPOSE_DATABASE_URL"] == db  # the api container uses the same remote stack
    assert got["COMPOSE_REDIS_URL"] == "redis://:pw@192.0.2.16:6380/0"


def test_devdb_remote_mysql_with_local_redis() -> None:
    """Live data on another machine's MySQL, sessions in this machine's Redis: the api container must reach that
    Redis by its compose service name, not 127.0.0.1 (which inside the container is the container itself)."""
    db = "mysql+pymysql://msp_dev_api:pw@192.0.2.16:3306/msp?charset=utf8mb4"
    got = _devdb({"DATABASE_URL": db, "INGEST_DATABASE_URL": db, "REDIS_URL": "redis://:rpw@127.0.0.1:6380/0"})
    assert got["DEV_DB_REMOTE"] == "1" and got["DEV_REDIS_REMOTE"] == ""
    assert (got["DEV_DB_HOST"], got["DEV_DB_PORT"]) == ("192.0.2.16", "3306")
    assert (got["DEV_REDIS_HOST"], got["DEV_REDIS_PORT"]) == ("127.0.0.1", "6380")
    assert got["COMPOSE_DATABASE_URL"] == db
    assert got["COMPOSE_REDIS_URL"] == "redis://:rpw@redis:6379/0"


def test_devdb_remote_mysql_without_redis_url_keeps_redis_local() -> None:
    """R2 (A10.5): a remote MySQL (URLs or MSP_DB_HOST) with REDIS_URL unset must not move Redis to the MySQL host."""
    db = "mysql+pymysql://msp_api:pw@192.0.2.16:3306/msp"
    for env in ({"DATABASE_URL": db, "INGEST_DATABASE_URL": db}, {"MSP_DB_HOST": "192.0.2.16"}):
        got = _devdb(env)
        assert got["DEV_DB_REMOTE"] == "1" and got["DEV_REDIS_REMOTE"] == ""
        assert (got["DEV_REDIS_HOST"], got["DEV_REDIS_PORT"]) == ("127.0.0.1", "6380")
        assert "COMPOSE_REDIS_URL" not in got  # the compose default redis:6379 is this machine's Redis


def test_test_backend_sets_redis_apart_from_mysql() -> None:
    """R1/R4 (A10.5): `make test-backend` gives pytest a Redis host of its own, never MSP_TEST_MYSQL_HOST."""
    _, body = _recipe("test-backend")
    recipe = "\n".join(body)
    assert "MSP_TEST_REDIS_HOST" in recipe and "MSP_TEST_REDIS_URL" in recipe
    assert not re.search(r"MSP_TEST_REDIS_HOST=[^;]*MSP_TEST_MYSQL_HOST", recipe)


def test_stack_up_starts_local_redis_when_only_mysql_is_remote() -> None:
    _, body = _recipe("stack-up")
    recipe = "\n".join(body)
    assert "DEV_REDIS_REMOTE" in recipe and "--no-recreate redis" in recipe


def test_devdb_explicit_compose_urls_win() -> None:
    got = _devdb({"MSP_DB_HOST": "192.0.2.16", "COMPOSE_DATABASE_URL": "mysql+pymysql://x:y@elsewhere:3306/msp"})
    assert got["DEV_DB_REMOTE"] == "1" and got["COMPOSE_DATABASE_URL"].endswith("@elsewhere:3306/msp")


def test_api_healthchecks_use_readiness() -> None:
    for text_ in (COMPOSE_DEV, COMPOSE_PROD):
        assert "/api/ready" in text_ and "/api/health'" not in text_


# ---- WP16: No-save is the default, enforced (DESIGN v0.5 B2) ----

_SAVED_ENV = (
    "DEFAULT_SESSION_MODE=saved\n"
    "MYSQL_ROOT_PASSWORD=not-a-secret\n"
    "REDIS_PASSWORD=not-a-secret\n"
    "COMPOSE_DATABASE_URL=mysql+pymysql://msp_api:x@mysql:3306/msp\n"
    "COMPOSE_REDIS_URL=redis://:x@redis:6379/0\n"
)


def _rendered_session_mode(tmp_path: Path, compose_file: str, *extra: str) -> dict[str, str | None]:
    """`docker compose config` of a repo compose file next to a `.env` that asks for Saved; mode per service."""
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:  # noqa: S603
        pytest.skip("docker compose is not installed")
    shutil.copy(REPO_ROOT / compose_file, tmp_path / compose_file)
    (tmp_path / ".env").write_text(_SAVED_ENV, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "DEFAULT_SESSION_MODE"))}
    out = subprocess.run(  # noqa: S603
        [docker, "compose", "-f", str(tmp_path / compose_file), *extra, "config", "--format", "json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    services = json.loads(out.stdout)["services"]
    return {name: (svc.get("environment") or {}).get("DEFAULT_SESSION_MODE") for name, svc in services.items()}


def test_ns2_prod_compose_pins_nosave_over_the_server_env(tmp_path: Path) -> None:
    """NS2: a server .env with DEFAULT_SESSION_MODE=saved still renders nosave for every app container."""
    modes = _rendered_session_mode(tmp_path, "docker-compose.prod.yml")
    assert modes["api"] == "nosave" and modes["purge"] == "nosave"


def test_ns3_dev_compose_pins_nosave_over_dotenv(tmp_path: Path) -> None:
    """NS3: same for the dev compose `api` service (profile `app`)."""
    modes = _rendered_session_mode(tmp_path, "docker-compose.yml", "--profile", "app")
    assert modes["api"] == "nosave"


class _StubApi(http.server.BaseHTTPRequestHandler):
    default_mode = "nosave"

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        bodies = {
            "/api/health": {"status": "ok"},
            "/api/ready": {"status": "ready"},
            "/api/config": {"plan_year": 2027, "default_mode": self.default_mode, "llm_enabled": False,
                            "llm_provider_label": "", "modes": ["nosave", "saved"]},
        }  # fmt: skip
        body = bodies.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def log_message(self, *args: object) -> None:
        pass


def _smoke_against(default_mode: str) -> subprocess.CompletedProcess[str]:
    handler = type("Stub", (_StubApi,), {"default_mode": default_mode})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return subprocess.run(  # noqa: S603
            [shutil.which("bash") or "/bin/bash", str(REPO_ROOT / "scripts" / "smoke.sh"), f"http://127.0.0.1:{srv.server_address[1]}"],
            capture_output=True, text=True, timeout=60,
        )  # fmt: skip
    finally:
        srv.shutdown()
        srv.server_close()


def test_ns7_smoke_fails_when_config_defaults_to_saved() -> None:
    """NS7: scripts/smoke.sh stops at GET /api/config when the API reports a Saved default."""
    got = _smoke_against("saved")
    assert got.returncode != 0
    assert "FAIL  GET /api/config" in got.stderr and "ok  GET /api/config" not in got.stdout


def test_ns7_smoke_accepts_a_nosave_default() -> None:
    got = _smoke_against("nosave")  # the stub has no /api/session, so the run fails at the next step
    assert "ok  GET /api/config" in got.stdout and "FAIL  GET /api/config" not in got.stderr
