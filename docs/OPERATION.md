# Operation: running, configuring and data stores

The detailed configuration for developers and operators (rule R-A: README keeps only an overview, a quick start and
links). Design background: [DESIGN.md](design/DESIGN.md) §10, [DESIGN-v0.4-ADDENDUM.md A10](design/DESIGN-v0.4-ADDENDUM.md)
(Redis is app-local) and [DESIGN-v0.5-ADDENDUM.md](design/DESIGN-v0.5-ADDENDUM.md). Production deployment:
[deploy/README.md](../deploy/README.md).

Contents: [Prerequisites](#prerequisites-on-a-fresh-ubuntu-2204-machine-once) · [Make targets](#make-targets) · [Configuration (.env)](#configuration-env) ·
[Local dev stack details](#local-dev-stack-details) · [Optional variations](#optional-variations) ·
[Data ingest](#data-ingest-cms-plan-year-2027) · [Data stores: rules and layouts](#data-stores-rules-thomas-2026-11-20)

## Prerequisites on a fresh Ubuntu 22.04 machine (once)
Docker Engine with the Compose v2 plugin, `make`, `git`, `curl`, `python3`, Node.js 20+
and [uv](https://docs.astral.sh/uv/) (uv downloads Python 3.13 itself):
```bash
sudo apt-get update && sudo apt-get install -y make git curl python3 ca-certificates
docker --version && docker compose version          # Docker Engine + compose plugin (docs.docker.com/engine/install/ubuntu)
curl -LsSf https://astral.sh/uv/install.sh | sh     # then open a new shell
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs
```
Free local ports: 3307 (MySQL), 6380 (Redis), 8000 (API), 8080 (web UI), 5173 (Vite, optional).

If `npm ci` was skipped, `make` stops with "frontend dependencies are not installed ... Run: (cd frontend && npm ci)".

## Make targets
| Target | What it does |
|---|---|
| `make stack-up` / `make stack-down` | dev MySQL + Redis (tmpfs, ports 3307/6380; only checked when `.env` points at another machine's stack) / stop everything |
| `make migrate` | Alembic to head + role grants (uses `MIGRATOR_DATABASE_URL`) |
| `make ingest-dev` | migrate + committed CMS fixtures + dev ZIP→county rows (no network) |
| `make dev-data` | `ingest-dev`, but only if the plan database is empty (run by `app-up`) |
| `make ingest` | migrate + real CMS 2027 ingest (network) |
| `make app-up` / `app-down` / `app-logs` | build + (re)start only the API and web containers (`${DOCKER_USER}/medicare-plan-selector[-web]:${IMAGE_TAG}`); starts MySQL/Redis if needed, never recreates them / stop all / follow logs |
| `make api-dev` / `make web-dev` | host-side API (:8000) / Vite dev server (:5173) |
| `make smoke` | end-to-end check of a running app (`SMOKE_URL`, default `http://${MSP_WEB_BIND:-127.0.0.1}:${MSP_WEB_PORT:-8080}`) |
| `make test` / `test-fast` / `lint` | full gate / unit tests without Docker / linters |
| `make purge` | retention purge (Saved sessions idle > `RETENTION_DAYS`, feedback > `FEEDBACK_RETENTION_DAYS`) |
| `make prod-config` / `prod-build` / `prod-up` / `prod-down` / `prod-logs` | production compose; see [deploy/README.md](../deploy/README.md) |


## Configuration (`.env`)
`.env` lives in the repo root (never committed, `chmod 600`). The Makefile, `selector` and Docker Compose read it;
blank numeric values (e.g. `LLM_PRICE_IN_PER_MTOK_USD=`) mean "use the default". Put comments on their own lines:
Compose does not strip `KEY=   # note` (the API treats a value starting with `#` as blank, but other tools may not). Host-side commands use `127.0.0.1:3307`/`:6380`;
containers use the service names (`mysql:3306`, `redis:6379`), which the dev compose sets for you (override with
`COMPOSE_DATABASE_URL` / `COMPOSE_REDIS_URL`; production requires them). Every key is documented in
[.env.example](../.env.example). The most important:

| Variable | Purpose |
|---|---|
| `DATABASE_URL`, `INGEST_DATABASE_URL`, `MIGRATOR_DATABASE_URL`, `REDIS_URL` | three MySQL roles (API read-only on plan data) and Redis |
| `DEFAULT_SESSION_MODE` | `nosave` (default) or `saved` |
| `PROFILE_ENC_KEY` | enables Saved mode (AES-GCM at rest); blank = No-save only |
| `LLM_PROVIDER`, `LLM_MODEL` | `anthropic` (design default), `xai`, `openai_compat`, `fake` (keyless demo) or blank (no-LLM) |
| `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `OPENAI_COMPAT_API_KEY` | key for the chosen provider only |
| `LLM_BASE_URL` | endpoint for `openai_compat` (e.g. `https://integrate.api.nvidia.com/v1`) |
| `LLM_DAILY_BUDGET_USD`, `LLM_PRICE_*`, `MAX_*` | cost cap and quotas (DESIGN §8.2); set `LLM_PRICE_*` for real usage or the budget cap never applies |
| `ADMIN_GATE_SECRET` | header nginx adds for `/admin`; blank = admin API off |
| `HUD_API_TOKEN` | live ZIP→county lookups (optional; fallback `selector hud load-file`, see [HUD setup](design/HUD-API-SETUP.md)) |
| `DOCKER_USER`, `IMAGE_TAG`, `APP_UID`, `APP_GID` | image names and the runtime user inside the images |
| `MSP_WEB_PORT`, `MSP_WEB_BIND` | dev web UI port and host IP (blank/unset = 127.0.0.1; a LAN IP for LAN access) |

## Local dev stack details
MySQL and Redis run on tmpfs: `make stack-down`/`app-down` (or a reboot) empties them. `make app-up` notices an
empty plan database and runs `make ingest-dev` by itself (`make dev-data` does only that step); a database that
already holds data, e.g. from `make ingest`, is left alone. If the data is still missing, the API reports not ready
(`curl http://127.0.0.1:8000/api/ready` shows the reason) and `make app-up` fails with the last API log lines instead
of starting a UI that only says "unavailable". To apply a changed mysql/redis compose config:
`make stack-down && make stack-up && make ingest-dev` (`stack-up` never recreates them).

**Gotcha:** host-side targets (`ingest-dev`, `migrate`, `dev-data`, `api-dev`) read `DATABASE_URL`,
`INGEST_DATABASE_URL`, `MIGRATOR_DATABASE_URL` and `REDIS_URL` from `.env`. There the DB URLs must point at
`127.0.0.1:3307` (or leave them out) or at the live-data MySQL, and `REDIS_URL` stays on `127.0.0.1:6380`; `mysql:3306` /
`redis:6379` only resolve inside containers, and `docker-compose.yml` sets those for the API container by itself.
Otherwise these targets fail with "Can't connect to MySQL server on 'mysql'".

The tests wipe `eph:*` and `quota:*` keys in the dev Redis, so don't run them while you test the UI.

**Web UI from another computer.** Either tunnel (`ssh -L 8080:127.0.0.1:8080 <host>`, then open
`http://127.0.0.1:8080` locally) or, on a trusted LAN, set `MSP_WEB_BIND=<the host's LAN IP>` (e.g. `192.168.0.216`)
in `.env`, run `make app-up`, and open `http://192.168.0.216:8080` (the UI then answers on that IP only; `0.0.0.0` =
every interface). Blank or unset `MSP_WEB_BIND` keeps it on 127.0.0.1. The dev UI has no login. The API always stays
on 127.0.0.1; MySQL and Redis do too unless `MSP_DB_BIND` is set.

## Optional variations
Edit `.env`, then run `make app-up` again to recreate the containers.
- **Saved mode:** set `PROFILE_ENC_KEY` (command in `.env.example`); the consent screen then offers "Save for 30 days"
  and the header shows "Delete my data".
- **Real assistant** (one of):
  - `LLM_PROVIDER=anthropic`, `LLM_MODEL=<model id>`, `ANTHROPIC_API_KEY=...`
  - `LLM_PROVIDER=xai`, `LLM_MODEL=<model id>`, `XAI_API_KEY=...`
  - any OpenAI-compatible endpoint, e.g. the NVIDIA API catalog (what QA used): `LLM_PROVIDER=openai_compat`,
    `LLM_BASE_URL=https://integrate.api.nvidia.com/v1`, `LLM_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b`,
    `OPENAI_COMPAT_API_KEY=nvapi-...`

  For real usage also set `LLM_PRICE_IN_PER_MTOK_USD` and `LLM_PRICE_OUT_PER_MTOK_USD` to the model's prices: while
  they are blank, cost counts as $0, so the `LLM_DAILY_BUDGET_USD` cap never triggers (only the per-session turn and
  token caps apply). Blank `LLM_PROVIDER` = no-LLM mode (form + table only).
- **Admin page:** set `ADMIN_GATE_SECRET`, then `curl -H "X-Admin-Gate: <secret>" http://127.0.0.1:8080/api/admin/summary`.
  In production nginx adds that header after basic auth; locally `/admin` shows "admin gate" without it.
- **Real CMS 2027 data:** `make ingest` (downloads several hundred MB the first time; all counties).
- **Host-side dev loop instead of Docker:** `make api-dev` (API on :8000 with reload) and `make web-dev`
  (Vite on http://localhost:5173, proxies `/api`); `make smoke SMOKE_URL=http://127.0.0.1:8000` checks the API.

## Data ingest (CMS plan year 2027)
```bash
make ingest                                     # = migrate + selector ingest --year 2027
(cd backend && uv run selector ingest --year 2027 --offline)    # reuse files already in data/raw/2027
```
- Sources are listed in `sources/2027.yaml`; raw files go to the git-ignored `data/raw/2027/`. The large Part D
  file is range-read, so only the needed members are downloaded.
- One transaction per plan year; it rolls back if validation fails, including the golden-row check for plan
  `H0028_028_0` in Maricopa County, AZ.
- If CMS republishes a file and its sha256 no longer matches `sources.lock`, the ingest stops. Review the change,
  then re-run with `--accept-new` and commit the updated `sources.lock`.
- ZIP→county: `HUD_API_TOKEN` + `selector hud preload --state AZ`, or without a token
  `selector hud load-file ZIP_COUNTY_<MMYYYY>.xlsx --state AZ`; unknown ZIPs fall back to a state/county picker.

## Data stores: rules (Thomas, 2026-11-20)
How to point the dev app and the test suite at MySQL and Redis.
- **Tests use this machine's MySQL only.** The suite creates and drops throwaway `msp_test_*` databases, so it runs
  against the local compose MySQL (`127.0.0.1:3307`), whose data can be thrown away. `backend/tests/conftest.py`
  refuses any `MSP_TEST_MYSQL_HOST` that is not this machine.
- **The MySQL at `192.168.0.216:3306` is for live data only.** The dev app on this machine reaches it through the
  DB URLs in `.env`. It is never used for tests.
- **Redis is app-local.** It runs in this machine's compose stack (`127.0.0.1:6380` on the host, `redis:6379` inside
  containers), on tmpfs with no persistence. A remote MySQL never implies a remote Redis.
- `/api/ready` is not ready unless both Redis and the plan data answer.

## Layouts

| Use | MySQL | Redis | How |
|---|---|---|---|
| Tests (`make test`) | local `127.0.0.1:3307` (throwaway `msp_test_*`) | local `127.0.0.1:6380` | Nothing to set. |
| Dev app, sample data | local `127.0.0.1:3307` | local `127.0.0.1:6380` | Local URLs in `.env` (as `.env.example`). |
| Dev app, live data | `192.168.0.216:3306` (`msp`) | local `127.0.0.1:6380` | Below. |
| Another machine's whole dev stack | that machine `:3307` | that machine `:6380` | Opt-in only (last section). |

## Dev app against the live-data MySQL

In `.env` on this machine (placeholder passwords; never commit `.env`):

```bash
DATABASE_URL=mysql+pymysql://msp_dev_api:<password>@192.168.0.216:3306/msp?charset=utf8mb4
INGEST_DATABASE_URL=mysql+pymysql://msp_dev_ingest:<password>@192.168.0.216:3306/msp?charset=utf8mb4
MIGRATOR_DATABASE_URL=mysql+pymysql://msp_dev_migrator:<password>@192.168.0.216:3306/msp?charset=utf8mb4
REDIS_URL=redis://:dev-redis-pw@127.0.0.1:6380/0   # or leave it out
MSP_DB_BIND=                                       # blank: this machine's Redis stays on loopback
```

`scripts/devdb.sh` sees that MySQL is not this machine (`MSP_DB_HOST` overrides the detection). Then:

- `make stack-up` starts only the local Redis and checks that the live MySQL answers;
- `make app-up` gives the api container the live MySQL URLs (`COMPOSE_*_DATABASE_URL`) and the local Redis
  (`redis:6379`). An explicit `COMPOSE_REDIS_URL` still wins. `make dev-data` (run by `app-up`) loads sample data
  only into an **empty** plan database, so it leaves the live data alone;
- `make migrate`, `make ingest` (real CMS data) and `make directories-sync` work on the live data.
  **Do not run `make ingest-dev` there:** it replaces the plan year's data with the committed sample fixtures.

## Tests

`make test` starts the local stack and runs lint, the backend suite and Vitest. The backend suite always uses this
machine's MySQL and Redis.

| Variable | Default | Notes |
|---|---|---|
| `MSP_TEST_MYSQL_HOST` | `127.0.0.1` | Must be this machine (loopback, its name or one of its addresses). `make test-backend` sets it to `MSP_DB_BIND` when that publishes the local stack on one LAN address. Anything else stops pytest. |
| `MSP_MYSQL_PORT` | `3307` | Local compose publish port. |
| `MSP_TEST_MIGRATOR_PASSWORD`, `MSP_TEST_INGEST_PASSWORD`, `MSP_TEST_API_PASSWORD` | compose dev passwords | Only if the local stack uses other passwords. |
| `MSP_TEST_REDIS_URL` | unset | Wins when set. |
| `MSP_TEST_REDIS_HOST` | `127.0.0.1` | Never the MySQL host. `make test-backend` sets it like `MSP_TEST_MYSQL_HOST`. |
| `MSP_REDIS_PORT` | `6380` | |
| `MSP_TEST_REDIS_PASSWORD` | `dev-redis-pw` | The local compose Redis password. |

Tests never read `.env`. The resolution is in `backend/tests/conftest.py` (`mysql_test_url`, `redis_test_url`,
`mysql_host_is_local`).

## Sharing this machine's whole dev stack (opt-in)

On the machine with the stack, set `MSP_DB_BIND=<its LAN IP>` in its `.env`, then
`make stack-down && make stack-up && make ingest-dev` (ports bind when containers are created). MySQL `:3307` and
Redis `:6380` then answer on that LAN address only. The dev passwords are public in this repo: trusted LAN only.
On the other host, put that address in the three DB URLs **and** in `REDIS_URL`. Only then is Redis remote.
