# medicare-plan-selector
This is an AI assistant that helps you choose the Medicare plan that best fits you.

## Overview
Medicare Plan Selector is a free, independent comparison tool. You describe your needs (ZIP code, Medicare
Advantage or Original Medicare + Part D, drugs, doctors, budget), and the assistant works from the official public
CMS plan data for your county to narrow the list to a cited top 3, with estimated yearly costs and a checklist. It
has no accounts, no commissions and no sponsored rankings. The backend is Python (FastAPI, SQLAlchemy, Alembic) on
MySQL 8.4 and Redis 7.4; the frontend is React + TypeScript + Vite.

> **Status:** work in progress on `feat/mvp`. Scaffold (WP0) and CMS data ingest (WP1) are done; the cost engine,
> chat agent and UI are being built (see [docs/CHANGELOG.md](docs/CHANGELOG.md)). The API currently serves
> `/api/health` only.

## Prerequisites
- Python 3.13 and [uv](https://docs.astral.sh/uv/) (CI pins uv 0.12.21)
- Node.js 20 and npm
- Docker with Compose v2
- Free local ports: **3307** (MySQL), **6380** (Redis), **8000** (API), **5173** (Vite dev server).
  Compose reads `MSP_MYSQL_PORT`, `MSP_REDIS_PORT` and `MSP_API_PORT` if you need different ports.

## Setup
```bash
git clone https://github.com/thomas-choi/medicare-plan-selector.git
cd medicare-plan-selector
cp .env.example .env        # never commit .env; keep it chmod 600
```

Fill in `.env` (every value in `.env.example` is a placeholder):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | MySQL URL for the API role `msp_api` (plan data read-only, user tables read-write) |
| `INGEST_DATABASE_URL` | MySQL URL for the ingest role `msp_ingest` (plan tables read-write) |
| `MIGRATOR_DATABASE_URL` | MySQL URL for the migration role `msp_migrator` (schema changes and grants) |
| `REDIS_URL`, `REDIS_PASSWORD` | Redis for No-save sessions and quota counters |
| `DEFAULT_SESSION_MODE` | `nosave` (default) or `saved` |
| `RETENTION_DAYS`, `FEEDBACK_RETENTION_DAYS` | How long Saved sessions and feedback are kept |
| `EPHEMERAL_IDLE_MINUTES`, `EPHEMERAL_MAX_HOURS`, `EPHEMERAL_END_GRACE_SECONDS` | No-save session lifetime |
| `PROFILE_ENC_KEY`, `PROFILE_KEY_VERSION` | Encryption key (and its version) for Saved-mode profiles and chat |
| `COOKIE_SECURE` | `true` in production; `false` only for plain-HTTP local testing |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL` | Chat model: `anthropic`, `openai_compat` (set `LLM_BASE_URL`) or `fake` (tests, no network) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_COMPAT_API_KEY` | Key for the chosen provider only |
| `LLM_FALLBACK_PROVIDER`, `LLM_FALLBACK_MODEL` | Optional fallback on provider errors or timeouts |
| `LLM_PRICE_IN_PER_MTOK_USD`, `LLM_PRICE_OUT_PER_MTOK_USD` | Model prices used for the daily budget. **Must be numbers** (use `0` with `fake`); blank values fail to load |
| `LLM_DAILY_BUDGET_USD`, `MAX_TURNS_PER_SESSION`, `MAX_TOKENS_PER_SESSION`, `MAX_SESSIONS_PER_IP_PER_DAY`, `CAPTCHA_PROVIDER` | Quotas and abuse controls |
| `HUD_API_TOKEN`, `HUD_API_BASE` | HUD USPS ZIP→county API. Optional for development and tests; needed for live ZIP lookups and `selector hud preload`. See [docs/design/HUD-API-SETUP.md](docs/design/HUD-API-SETUP.md), which also describes the HUD quarterly-file fallback |
| `PLAN_YEAR`, `MED_PUBLIC_PORT` | Active plan year (2027) and the public HTTPS port for deployment |

Generate the encryption key (32 random bytes, base64):
```bash
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

**Running `selector` commands on your machine against the local stack:** `.env.example` uses the container host
names (`mysql:3306`, `redis:6379`). For host-side commands point the URLs at `127.0.0.1:3307` and `127.0.0.1:6380`
and use the local-only dev passwords from `deploy/mysql/01-roles.sql` and `docker-compose.yml`. Settings are read
from the environment (or from a `.env` in the current directory, which is `backend/` for the Makefile targets), so
export them first:
```bash
set -a; . ./.env; set +a
```

## Build
```bash
cd backend && uv sync --frozen && cd ..                 # backend + dev tools from uv.lock
cd frontend && npm ci && npm run build && cd ..         # frontend into frontend/dist/
docker compose --profile app build api                  # API image (backend/Dockerfile)
```

## Start and stop
```bash
make stack-up                                   # MySQL 8.4 on 127.0.0.1:3307, Redis 7.4 on 127.0.0.1:6380
make migrate                                    # Alembic upgrade + table grants (uses MIGRATOR_DATABASE_URL)
docker compose --profile app up -d api          # API on http://127.0.0.1:8000 (health: /api/health)
cd frontend && npm run dev                      # UI on http://localhost:5173, proxies /api to :8000
```
Stop everything with `docker compose --profile app down` (`make stack-down` runs `docker compose down`).

The dev stack keeps MySQL and Redis on tmpfs: **all data is lost when the containers stop**, so re-run
`make migrate` and the ingest after every restart. Redis runs with persistence off by design.

## Data ingest (CMS plan year 2027)
After `make stack-up` and `make migrate`, with the environment exported:
```bash
cd backend
uv run selector ingest --year 2027              # download, check sha256 against sources.lock, load, validate
uv run selector ingest --year 2027 --offline    # reuse files already in data/raw/2027 (no network)
```
- Sources are listed in `sources/2027.yaml`; raw files go to the git-ignored `data/raw/2027/`. The large Part D
  file is range-read, so only the needed members are downloaded.
- The load runs in one transaction per plan year and rolls back if validation fails, including the golden-row
  check for plan `H0028_028_0` in Maricopa County, AZ.
- If CMS republishes a file and its sha256 no longer matches `sources.lock`, the ingest stops. Review the change,
  then re-run with `--accept-new` and commit the updated `sources.lock`.
- The first run is network-bound; `--offline` re-runs are much faster. Re-run the ingest after each stack restart.

## Tests
```bash
make test-fast      # backend unit tests (no Docker) + frontend Vitest
make test           # full gate: lint (ruff, mypy, tsc, eslint, prettier) + every backend test + Vitest; starts the stack
make lint           # linters only
make precommit      # pre-commit: gitleaks, forbidden-file check, linters
```
Tests marked `infra` need the compose MySQL/Redis stack; `make test` brings it up. Tests use their own throwaway
databases and never need a real `.env` or LLM key. CI (`.github/workflows/ci.yml`) runs `make test` with
`LLM_PROVIDER=fake`.

## Session modes
- **No-save (default):** your profile and chat live only in Redis, encrypted with a per-session key held in your
  browser cookie, and are wiped when the session ends or expires. Nothing is written to MySQL except anonymous
  counters and any message you choose to send to the team.
- **Saved:** opt in on the consent screen to keep your session for `RETENTION_DAYS`, with the profile and chat
  encrypted at rest. You can delete your data at any time.

Details: [DESIGN §8.5](docs/design/DESIGN.md). (The session UI is part of the MVP work still in progress.)

## Docs
- [Design v0.3](docs/design/DESIGN.md) and [design index](docs/design/README.md)
- [Implementation plan](docs/design/IMPLEMENTATION-PLAN.md) and [open questions](docs/design/OPEN-QUESTIONS.md)
- [HUD API setup](docs/design/HUD-API-SETUP.md)
- [Data sources and attribution](docs/DATA-SOURCES.md)
- [Security](docs/SECURITY.md) · [Contributing](docs/CONTRIBUTING.md) · [Changelog](docs/CHANGELOG.md)

## Disclaimer
This is an independent, free comparison tool. It is **not** a licensed insurance agent or broker, and it is **not
affiliated with or endorsed by CMS, Medicare or any plan**. Costs are estimates. Always confirm plan details on the
[Medicare.gov Plan Finder](https://www.medicare.gov/plan-compare/), at 1-800-MEDICARE, or with your
[SHIP counselor](https://www.shiphelp.org/local-medicare-help).

## License
[GPL-3.0](LICENSE)
