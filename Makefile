# Medicare Plan Selector — developer entry points. `make test` is the gate for every work package.
SHELL := /bin/bash
UV := uv run --project backend
COMPOSE := docker compose

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
        precommit build-frontend

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







precommit:  ## run before every proposed commit (gitleaks, forbidden files, linters)
	$(UV) pre-commit run --all-files

build-frontend:
	cd frontend && npm run build
