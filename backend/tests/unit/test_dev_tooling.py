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
# .env.prod for DigitalOcean Managed MySQL: no MySQL container, TLS with the DO CA certificate.
_DO_CA = "./cert/do.ca.crt"  # MSP_DB_CA_FILE, relative to the repo root
_PROD_SAVED_ENV = (
    "DEFAULT_SESSION_MODE=saved\n"
    "REDIS_PASSWORD=not-a-secret\n"
    f"MSP_DB_CA_FILE={_DO_CA}\n"
    "DATABASE_URL=mysql+pymysql://msp_api:x@db-mysql-example.db.ondigitalocean.com:25060/msp\n"
)


def _render(tmp_path: Path, compose_file: str, env_files: dict[str, str], *args: str) -> dict[str, dict]:
    """`docker compose <args> config` of a repo compose file in `tmp_path` next to `env_files`; services."""
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:  # noqa: S603
        pytest.skip("docker compose is not installed")
    shutil.copy(REPO_ROOT / compose_file, tmp_path / compose_file)
    for name, text_ in env_files.items():
        (tmp_path / name).write_text(text_, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "DEFAULT_SESSION_MODE"))}
    env = {k: v for k, v in env.items() if k not in ("MYSQL_ROOT_PASSWORD", "REDIS_PASSWORD")}
    out = subprocess.run(  # noqa: S603
        [docker, "compose", *args, "-f", str(tmp_path / compose_file), "config", "--format", "json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)["services"]


def _modes(services: dict[str, dict]) -> dict[str, str | None]:
    return {name: (svc.get("environment") or {}).get("DEFAULT_SESSION_MODE") for name, svc in services.items()}


PROD_ARGS = ("--env-file", ".env.prod")


def test_ns2_prod_compose_pins_nosave_over_the_server_env(tmp_path: Path) -> None:
    """NS2: a .env.prod with DEFAULT_SESSION_MODE=saved still renders nosave for every app container."""
    modes = _modes(_render(tmp_path, "docker-compose.prod.yml", {".env.prod": _PROD_SAVED_ENV}, *PROD_ARGS))
    assert modes["api"] == "nosave" and modes["purge"] == "nosave"


def test_ns3_dev_compose_pins_nosave_over_dotenv(tmp_path: Path) -> None:
    """NS3: same for the dev compose `api` service (profile `app`)."""
    modes = _modes(_render(tmp_path, "docker-compose.yml", {".env": _SAVED_ENV}, "--profile", "app"))
    assert modes["api"] == "nosave"


def test_prod_compose_reads_env_prod_not_the_dev_env(tmp_path: Path) -> None:
    """Production settings come only from .env.prod; a dev .env in the same directory is ignored."""
    assert re.search(r"env_file:\n\s*- path: \.env\.prod\n\s*required: true", COMPOSE_PROD)
    assert not re.search(r"- path: \.env\n", COMPOSE_PROD)
    assert re.search(r"^PROD_ENV \?= \.env\.prod$", MAKEFILE, re.M)
    assert (
        "COMPOSE_PROD = env $(PROD_KEYS) docker compose --env-file $(PROD_ENV) -f docker-compose.prod.yml" in MAKEFILE
    )
    dev = (
        "REDIS_PASSWORD=dev-redis-pw\nDATABASE_URL=mysql+pymysql://msp_api:dev-api-pw@127.0.0.1:3307/msp\n"
        "MSP_DB_CA_FILE=/dev/null\nDEV_ONLY=1\n"
    )
    prod = _PROD_SAVED_ENV.replace("REDIS_PASSWORD=not-a-secret", "REDIS_PASSWORD=prod-only-value") + "PROD_ONLY=1\n"
    services = _render(tmp_path, "docker-compose.prod.yml", {".env": dev, ".env.prod": prod}, *PROD_ARGS)
    assert services["redis"]["environment"]["REDIS_PASSWORD"] == "prod-only-value"
    assert services["api"]["environment"]["REDIS_URL"] == "redis://:prod-only-value@redis:6379/0"
    assert "ondigitalocean.com:25060" in services["api"]["environment"]["DATABASE_URL"]
    # `config` inlines env_file into environment: the containers get .env.prod's keys and none of .env's.
    assert services["api"]["environment"].get("PROD_ONLY") == "1" and "DEV_ONLY" not in services["api"]["environment"]


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


@pytest.mark.parametrize(
    ("bind", "host"),
    [("", "127.0.0.1"), ("MSP_WEB_BIND=0.0.0.0\n", "127.0.0.1"), ("MSP_WEB_BIND=192.168.0.9\n", "192.168.0.9")],
)
def test_prod_up_smoke_calls_the_bound_address(tmp_path: Path, bind: str, host: str) -> None:
    env_prod = tmp_path / ".env.prod"
    env_prod.write_text(f"DATABASE_URL=mysql+pymysql://u:pw@h:25060/msp\n{bind}")
    out = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-s", "prod-up", f"PROD_ENV={env_prod}"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
    ).stdout  # fmt: skip
    assert f'scripts/smoke.sh "http://{host}:8080"' in out


@pytest.mark.parametrize(
    ("extra", "tail"),
    [([], "build"), (["api"], "build api"), (["web", "api"], "build web api"),
     (["--", "--no-cache", "api"], "build --no-cache api")],
)  # fmt: skip
def test_prod_build_passes_extra_words_to_compose_build(tmp_path: Path, extra: list[str], tail: str) -> None:
    env_prod = tmp_path / ".env.prod"
    env_prod.write_text("DATABASE_URL=mysql+pymysql://u:pw@h:25060/msp\n")
    out = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-s", f"PROD_ENV={env_prod}", "prod-build", *extra],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
    ).stdout  # fmt: skip
    compose = [ln for ln in out.splitlines() if "docker compose" in ln]  # `make -n` also lists the no-op `:`
    assert len(compose) == 1 and compose[0].rstrip().endswith(f"-f docker-compose.prod.yml {tail}")


def test_smoke_rejects_an_unknown_data_mode() -> None:
    got = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "/bin/bash", str(REPO_ROOT / "scripts" / "smoke.sh"), "http://127.0.0.1:9"],
        capture_output=True, text=True, timeout=30, env={**os.environ, "SMOKE_DATA": "prod"},
    )  # fmt: skip
    assert got.returncode == 2 and "SMOKE_DATA must be sample or real" in got.stderr


def test_make_smoke_defaults_to_sample_data() -> None:
    out = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-s", "smoke"], cwd=REPO_ROOT, capture_output=True, text=True,
        timeout=30, check=True,
    ).stdout  # fmt: skip
    assert 'SMOKE_DATA="${SMOKE_DATA:-sample}" bash scripts/smoke.sh' in out


def test_prod_compose_uses_managed_mysql_over_tls(tmp_path: Path) -> None:
    """Production MySQL is DO Managed MySQL: no MySQL container or port, MSP_DB_CA_FILE is mounted read-only at
    /run/msp/do.ca.crt and the containers' MSP_DB_CA_FILE names that path, and the app containers get only the API
    role."""
    services = _render(tmp_path, "docker-compose.prod.yml", {".env.prod": _PROD_SAVED_ENV}, *PROD_ARGS)
    assert "mysql" not in services and "MYSQL_ROOT_PASSWORD" not in COMPOSE_PROD
    assert [p["target"] for svc in services.values() for p in svc.get("ports", [])] == [8080]
    for name in ("api", "purge"):
        env = services[name]["environment"]
        assert env["DATABASE_URL"].endswith(":25060/msp") and env["MSP_DB_CA_FILE"] == "/run/msp/do.ca.crt", name
        assert env["INGEST_DATABASE_URL"] == "" and env["MIGRATOR_DATABASE_URL"] == "", name
        assert [(v["source"], v["target"], v.get("read_only")) for v in services[name]["volumes"]] == [
            (str(tmp_path / "cert" / "do.ca.crt"), "/run/msp/do.ca.crt", True)
        ], name


def test_prod_targets_ignore_stale_shell_copies_of_env_prod_keys(tmp_path: Path) -> None:
    """A `DATABASE_URL` still exported in the shell (from `set -a; . ./.env.prod` with an older file) must not reach
    Compose: every key that .env.prod defines is removed from the environment of `make prod-*`."""
    env_prod = tmp_path / ".env.prod"
    env_prod.write_text(
        "# comment\nDATABASE_URL=mysql+pymysql://new:x@h/msp\nexport REDIS_PASSWORD=x\n  MSP_DB_CA_FILE=./c\n"
    )
    out = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-s", "prod-up", f"PROD_ENV={env_prod}"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
        env={**os.environ, "DATABASE_URL": "mysql+pymysql://stale:x@h/msp"},
    )  # fmt: skip
    cmd = next(ln for ln in out.stdout.splitlines() if ln.endswith("up -d --wait"))
    assert cmd.startswith("env -u DATABASE_URL -u REDIS_PASSWORD -u MSP_DB_CA_FILE docker compose --env-file "), cmd


def test_prod_api_database_url_comes_only_from_env_prod(tmp_path: Path) -> None:
    """Even `docker compose` run by hand with a stale exported DATABASE_URL gives the containers .env.prod's value:
    the compose file no longer interpolates ${DATABASE_URL}, `env_file` supplies it."""
    assert "${DATABASE_URL" not in COMPOSE_PROD
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:  # noqa: S603
        pytest.skip("docker compose is not installed")
    shutil.copy(REPO_ROOT / "docker-compose.prod.yml", tmp_path / "docker-compose.prod.yml")
    (tmp_path / ".env.prod").write_text(_PROD_SAVED_ENV, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    env["DATABASE_URL"] = "mysql+pymysql://stale_user:x@old-host:25060/msp"
    out = subprocess.run(  # noqa: S603
        [docker, "compose", "--env-file", ".env.prod", "-f", "docker-compose.prod.yml", "config", "--format", "json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    for name in ("api", "purge"):
        url = json.loads(out.stdout)["services"][name]["environment"]["DATABASE_URL"]
        assert url.startswith("mysql+pymysql://msp_api:") and "stale_user" not in url, name


def test_prod_up_checks_the_config_waits_for_health_and_runs_the_smoke_test(tmp_path: Path) -> None:
    env_prod = tmp_path / ".env.prod"
    env_prod.write_text("DATABASE_URL=mysql+pymysql://u:secret-pw@h:25060/msp\nMSP_WEB_PORT=8181  # web\n")
    out = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-s", "prod-up", f"PROD_ENV={env_prod}"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
    ).stdout  # fmt: skip
    lines = [ln for ln in out.splitlines() if "docker compose" in ln or "smoke.sh" in ln]
    assert "config --quiet" in lines[0] and lines[1].endswith("up -d --wait")
    assert 'SMOKE_DATA=real bash scripts/smoke.sh "http://127.0.0.1:8181"' in lines[2]  # real CMS data, no golden row
    assert "secret-pw" not in out  # the URL is checked with grep, never put on a command line


@pytest.mark.parametrize(
    ("hud_file", "expect"), [("", "hud preload --state All"), ("x/ZIP_COUNTY_062026.xlsx", "hud load-file")]
)
def test_zip_data_uses_the_file_or_the_hud_api(hud_file: str, expect: str) -> None:
    out = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-s", "zip-data", f"HUD_FILE={hud_file}"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
    ).stdout  # fmt: skip
    assert "hud preload --state All" in out and "hud load-file" in out  # one shell `if`, both branches
    if hud_file:
        assert str(REPO_ROOT / hud_file) in out  # made absolute (the command runs in backend/)
    else:
        assert 'if [ -n "" ]' in out
    assert expect in out
