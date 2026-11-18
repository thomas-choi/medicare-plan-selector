# Medicare Plan Selector — developer entry points. `make test` is the gate for every work package.
SHELL := /bin/bash
UV := uv run --project backend
COMPOSE := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml

# Host-side commands read the repo-root .env if it exists (export-style, like `set -a; . ./.env`), then fall back
# to the local dev stack: MySQL on 127.0.0.1:3307 and Redis on 127.0.0.1:6380 with the dev-only passwords from
# deploy/mysql/01-roles.sql and docker-compose.yml. Containers use the service names (mysql:3306, redis:6379).
LOAD_ENV := set -a; [ ! -f $(CURDIR)/.env ] || . $(CURDIR)/.env; set +a;
DEV_DB := \
  MIGRATOR_DATABASE_URL="$${MIGRATOR_DATABASE_URL:-mysql+pymysql://msp_migrator:dev-migrator-pw@127.0.0.1:3307/msp}" \
  INGEST_DATABASE_URL="$${INGEST_DATABASE_URL:-mysql+pymysql://msp_ingest:dev-ingest-pw@127.0.0.1:3307/msp}" \
  DATABASE_URL="$${DATABASE_URL:-mysql+pymysql://msp_api:dev-api-pw@127.0.0.1:3307/msp}" \
  REDIS_URL="$${REDIS_URL:-redis://:dev-redis-pw@127.0.0.1:6380/0}"
SELECTOR := @cd backend && $(LOAD_ENV) env $(DEV_DB) uv run selector

.PHONY: help stack-up stack-down lint test test-fast test-backend test-frontend migrate ingest-dev ingest \
        api-dev web-dev app-up app-down app-logs precommit build-frontend purge smoke \
        prod-config prod-build prod-up prod-down prod-logs

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1

stack-up:  ## MySQL 8.4 (:3307) and Redis 7.4 (:6380, no persistence) for tests
	$(COMPOSE) up -d --wait mysql redis

stack-down:
	$(COMPOSE) --profile app down

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && npx tsc --noEmit && npx eslint . && npx prettier --check .

test-fast:  ## unit tests only, no Docker
	cd backend && uv run pytest -q -m "not infra"
	cd frontend && npx vitest run

test-backend: stack-up
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && npx vitest run

test: lint test-backend test-frontend  ## the full cumulative regression suite

migrate:  ## upgrade the schema and apply role grants (uses MIGRATOR_DATABASE_URL)
	$(SELECTOR) migrate up
	$(SELECTOR) db-grants

ingest-dev: migrate  ## dev data: committed CMS sample fixtures (Maricopa, AZ) + dev ZIP→county rows, no network
	$(SELECTOR) ingest --year 2027 --fixtures
	$(SELECTOR) hud load-file tests/fixtures/hud/zip_county_dev.csv --year 2026 --quarter 2

ingest: migrate  ## real CMS 2027 ingest (downloads ~hundreds of MB the first time)
	$(SELECTOR) ingest --year 2027

purge:  ## retention purge (Saved sessions idle > RETENTION_DAYS, old feedback)
	$(SELECTOR) purge

api-dev:  ## API on the host at http://127.0.0.1:8000 (reload on change)
	cd backend && $(LOAD_ENV) env $(DEV_DB) COOKIE_SECURE=false uv run selector ephemeral-flush
	cd backend && $(LOAD_ENV) env $(DEV_DB) COOKIE_SECURE=false \
	  uv run uvicorn --factory selector.api.main:app_factory --host 127.0.0.1 --port 8000 --reload --no-access-log

web-dev:  ## Vite dev server at http://localhost:5173 (proxies /api to :8000)
	cd frontend && npm run dev

app-up:  ## whole stack in Docker: MySQL, Redis, API and the nginx web UI on http://127.0.0.1:$${MSP_WEB_PORT:-8080}
	$(COMPOSE) --profile app up -d --build --wait

app-down:
	$(COMPOSE) --profile app down

app-logs:
	$(COMPOSE) --profile app logs -f api web

precommit:  ## run before every proposed commit (gitleaks, forbidden files, linters)
	$(UV) pre-commit run --all-files

build-frontend:
	cd frontend && npm run build

smoke:  ## quick check of a running app (make app-up or api-dev): config, a No-save session and a Maricopa compare
	@bash scripts/smoke.sh "$${SMOKE_URL:-http://127.0.0.1:$${MSP_WEB_PORT:-8080}}"

# ---- production (docker-compose.prod.yml; needs the server .env, see deploy/README.md) ----
prod-config:  ## validate the production compose file against .env (prints no secrets)
	$(COMPOSE_PROD) config --quiet && echo "docker-compose.prod.yml OK"

prod-build:
	$(COMPOSE_PROD) build

prod-up:
	$(COMPOSE_PROD) up -d --wait

prod-down:
	$(COMPOSE_PROD) down

prod-logs:
	$(COMPOSE_PROD) logs -f api web purge
