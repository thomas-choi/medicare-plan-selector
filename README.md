# medicare-plan-selector
This is an AI assistant that helps you choose the Medicare plan that best fits you.

## Overview
Medicare Plan Selector is a free, independent comparison tool. You describe your needs (ZIP code, Medicare
Advantage or Original Medicare + Part D, drugs, doctors, budget), and the assistant works from the official public
CMS plan data for your county to narrow the list to a cited top 3, with estimated yearly costs and a checklist. It
has no accounts, no commissions and no sponsored rankings. The backend is Python (FastAPI, SQLAlchemy, Alembic) on
MySQL 8.4 and Redis 7.4; the frontend is React + TypeScript + Vite.

> **Status:** MVP on branch `feat/mvp-wp2-8` (WP0–WP8; see [docs/CHANGELOG.md](docs/CHANGELOG.md)). Runs end to
> end locally with committed sample data for Maricopa County, AZ and a keyless demo assistant (`LLM_PROVIDER=fake`).

## Test run on a fresh machine (Ubuntu 22.04, e.g. ml3090)
Copy-paste friendly. Nothing here needs an API key; nothing is pushed or deployed.

**0. Prerequisites (once).** Docker Engine with the Compose v2 plugin, `make`, `git`, `curl`, `python3`, Node.js 20+
and [uv](https://docs.astral.sh/uv/) (uv downloads Python 3.13 itself):
```bash
sudo apt-get update && sudo apt-get install -y make git curl python3 ca-certificates
docker --version && docker compose version          # Docker Engine + compose plugin (docs.docker.com/engine/install/ubuntu)
curl -LsSf https://astral.sh/uv/install.sh | sh     # then open a new shell
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs
```
Free local ports: 3307 (MySQL), 6380 (Redis), 8000 (API), 8080 (web UI), 5173 (Vite, optional).

**1. Get the branch and install.**
```bash
git clone https://github.com/thomas-choi/medicare-plan-selector.git   # or: cd medicare-plan-selector && git fetch
cd medicare-plan-selector
git checkout feat/mvp-wp2-8
cp .env.example .env && chmod 600 .env     # works as-is for local testing (LLM_PROVIDER=fake, dev passwords)
(cd backend && uv sync --frozen)
(cd frontend && npm ci)
```

**2. Run the whole regression suite** (lint + every backend test incl. No-save N1–N9 backend parts + Vitest).
It starts MySQL and Redis in Docker; tests use throwaway `msp_test_*` databases and never call an LLM:
```bash
make test
```
Expected: ruff/mypy/tsc/eslint/prettier clean, ~290 backend tests passed, ~20 Vitest tests passed.
(The tests wipe `eph:*` and `quota:*` keys in the dev Redis, so don't run them while you test the UI.)

**3. Load dev data and start the app in Docker.**
```bash
make stack-up        # MySQL 127.0.0.1:3307 + Redis 127.0.0.1:6380 (both tmpfs: data is gone after stack-down)
make ingest-dev      # schema + grants + committed CMS sample fixtures (Maricopa/Pinal, AZ) + dev ZIP→county rows
make app-up          # builds and starts the API and the web UI → http://127.0.0.1:8080
make smoke           # health, config, No-save session, ZIP lookups, Maricopa compare with the golden H0028_028_0 row, chat, erase
```
Open **http://127.0.0.1:8080** (from another computer: `ssh -L 8080:127.0.0.1:8080 ml3090`, then open the same URL
locally). Try: Start (No-save) → ZIP `85004` → Find county → drug "metformin" with RxCUI `197361` → Compare plans →
ask the assistant "Explain H0028_028_0" → Cost chart / Side-by-side / Checklist → Download comparison → End
session & erase. ZIP `85142` shows the split-county picker. Drug *search* calls RxNav (internet); the RxCUI field
works offline. The dev sample data only covers Maricopa and Pinal counties.

**4. Optional variations** (edit `.env`, then `make app-up` again to recreate the containers):
- **Saved mode:** set `PROFILE_ENC_KEY` (command in `.env.example`); the consent screen then offers "Save for 30 days"
  and the header shows "Delete my data".
- **Real assistant:** `LLM_PROVIDER=anthropic`, `LLM_MODEL=<model id>`, `ANTHROPIC_API_KEY=...` — or
  `LLM_PROVIDER=xai`, `LLM_MODEL=<model id>`, `XAI_API_KEY=...`. Set `LLM_PRICE_*` so the daily budget counts.
  Blank `LLM_PROVIDER` = no-LLM mode (form + table only).
- **Admin page:** set `ADMIN_GATE_SECRET`, then `curl -H "X-Admin-Gate: <secret>" http://127.0.0.1:8080/api/admin/summary`.
  In production nginx adds that header after basic auth; locally `/admin` shows "admin gate" without it.
- **Real CMS 2027 data:** `make ingest` (downloads several hundred MB the first time; all counties).
- **Host-side dev loop instead of Docker:** `make api-dev` (API on :8000 with reload) and `make web-dev`
  (Vite on http://localhost:5173, proxies `/api`); `make smoke SMOKE_URL=http://127.0.0.1:8000` checks the API.

**5. Stop.** `make app-down` (or `make stack-down`); this also wipes the tmpfs databases.

## Make targets
| Target | What it does |
|---|---|
| `make stack-up` / `make stack-down` | dev MySQL + Redis (tmpfs, ports 3307/6380) / stop everything |
| `make migrate` | Alembic to head + role grants (uses `MIGRATOR_DATABASE_URL`) |
| `make ingest-dev` | migrate + committed CMS fixtures + dev ZIP→county rows (no network) |
| `make ingest` | migrate + real CMS 2027 ingest (network) |
| `make app-up` / `app-down` / `app-logs` | API + web containers (`${DOCKER_USER}/medicare-plan-selector[-web]:${IMAGE_TAG}`) |
| `make api-dev` / `make web-dev` | host-side API (:8000) / Vite dev server (:5173) |
| `make smoke` | end-to-end check of a running app (`SMOKE_URL`, default http://127.0.0.1:8080) |
| `make test` / `test-fast` / `lint` | full gate / unit tests without Docker / linters |
| `make purge` | retention purge (Saved sessions idle > `RETENTION_DAYS`, feedback > `FEEDBACK_RETENTION_DAYS`) |
| `make prod-config` / `prod-build` / `prod-up` / `prod-down` / `prod-logs` | production compose; see [deploy/README.md](deploy/README.md) |

## Configuration (`.env`)
`.env` lives in the repo root (never committed, `chmod 600`). The Makefile and `selector` read it; blank numeric
values (e.g. `LLM_PRICE_IN_PER_MTOK_USD=`) mean "use the default". Host-side commands use `127.0.0.1:3307`/`:6380`;
containers use the service names (`mysql:3306`, `redis:6379`), which the dev compose sets for you (override with
`COMPOSE_DATABASE_URL` / `COMPOSE_REDIS_URL`; production requires them). Every key is documented in
[.env.example](.env.example). The most important:

| Variable | Purpose |
|---|---|
| `DATABASE_URL`, `INGEST_DATABASE_URL`, `MIGRATOR_DATABASE_URL`, `REDIS_URL` | three MySQL roles (API read-only on plan data) and Redis |
| `DEFAULT_SESSION_MODE` | `nosave` (default) or `saved` |
| `PROFILE_ENC_KEY` | enables Saved mode (AES-GCM at rest); blank = No-save only |
| `LLM_PROVIDER`, `LLM_MODEL` | `anthropic` (design default), `xai`, `openai_compat`, `fake` (keyless demo) or blank (no-LLM) |
| `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `OPENAI_COMPAT_API_KEY` | key for the chosen provider only |
| `LLM_DAILY_BUDGET_USD`, `LLM_PRICE_*`, `MAX_*` | cost cap and quotas (DESIGN §8.2) |
| `ADMIN_GATE_SECRET` | header nginx adds for `/admin`; blank = admin API off |
| `HUD_API_TOKEN` | live ZIP→county lookups (optional; fallback `selector hud load-file`, see [HUD setup](docs/design/HUD-API-SETUP.md)) |
| `DOCKER_USER`, `IMAGE_TAG`, `APP_UID`, `APP_GID` | image names and the runtime user inside the images |

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

## Session modes
- **No-save (default):** your profile and chat live only in Redis, encrypted with a per-session key held in your
  browser cookie, and are wiped when you end the session, after 30 minutes idle, after 4 hours at most, or when the
  API restarts. Nothing is written to MySQL except anonymous counters and any message you choose to send to the team.
- **Saved:** opt in on the consent screen to keep your session for `RETENTION_DAYS`, with the ZIP, drugs, doctors
  and chat encrypted at rest. "Delete my data" removes it at any time.

Details: [DESIGN §8.5](docs/design/DESIGN.md).

## Docs
- [Design v0.3](docs/design/DESIGN.md) and [design index](docs/design/README.md)
- [Implementation plan](docs/design/IMPLEMENTATION-PLAN.md) and [open questions](docs/design/OPEN-QUESTIONS.md)
- [HUD API setup](docs/design/HUD-API-SETUP.md) · [Deployment](deploy/README.md)
- [Data sources and attribution](docs/DATA-SOURCES.md)
- [Security](docs/SECURITY.md) · [Contributing](docs/CONTRIBUTING.md) · [Changelog](docs/CHANGELOG.md)

## Disclaimer
This is an independent, free comparison tool. It is **not** a licensed insurance agent or broker, and it is **not
affiliated with or endorsed by CMS, Medicare or any plan**. Costs are estimates. Always confirm plan details on the
[Medicare.gov Plan Finder](https://www.medicare.gov/plan-compare/), at 1-800-MEDICARE, or with your
[SHIP counselor](https://www.shiphelp.org/local-medicare-help).

## License
[GPL-3.0](LICENSE)
