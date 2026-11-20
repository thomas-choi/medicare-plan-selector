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
# Frontend tools come only from frontend/node_modules, never from the npm registry on the fly: without
# node_modules, `npx tsc` downloads an unrelated npm package that happens to be called `tsc` (QA #3).
NODE_BIN := ./node_modules/.bin

.PHONY: help frontend-deps stack-up local-stack-up stack-down lint test test-fast test-backend test-frontend migrate ingest-dev ingest \
        directories-sync \
        api-dev web-dev dev-data app-up app-down app-logs precommit build-frontend purge smoke \
        prod-config prod-build prod-up prod-down prod-logs

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1

# Where the dev MySQL/Redis live (local stack, or another machine's stack named in .env): see scripts/devdb.sh.
DEVDB := $(LOAD_ENV) . $(CURDIR)/scripts/devdb.sh;

# --no-recreate: the dev MySQL runs on tmpfs, so recreating it (compose does that whenever its config changes)
# would silently wipe the schema and data. To apply a changed mysql/redis config: make stack-down && make stack-up.
# When .env points the URLs at another machine (e.g. ml3090 using ml3060's stack), only check that it answers.
stack-up:  ## MySQL 8.4 (:3307) and Redis 7.4 (:6380, no persistence) for the app; local, or the remote one in .env
	@$(DEVDB) if [ -n "$$DEV_DB_REMOTE" ]; then devdb_check_remote; else $(MAKE) --no-print-directory local-stack-up; fi

# Always this machine's stack: the backend tests create msp_test_* databases and drive `docker compose` themselves.
local-stack-up:
	$(COMPOSE) up -d --wait --no-recreate mysql redis

stack-down:
	$(COMPOSE) --profile app down

frontend-deps:
	@for t in tsc eslint prettier vitest; do \
	  if [ ! -x frontend/node_modules/.bin/$$t ]; then \
	    echo "ERROR: frontend dependencies are not installed (frontend/node_modules/.bin/$$t is missing)." >&2; \
	    echo "       Run:  (cd frontend && npm ci)   then re-run make." >&2; \
	    exit 1; \
	  fi; \
	done

lint: frontend-deps
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && $(NODE_BIN)/tsc --noEmit && $(NODE_BIN)/eslint . && $(NODE_BIN)/prettier --check .

test-fast: frontend-deps  ## unit tests only, no Docker
	cd backend && uv run pytest -q -m "not infra"
	cd frontend && $(NODE_BIN)/vitest run

# Tests use the local stack on 127.0.0.1, or on MSP_DB_BIND when that publishes it on one LAN address only.
test-backend: local-stack-up
	@bind=$$($(LOAD_ENV) printf %s "$${MSP_DB_BIND:-}"); case "$$bind" in ""|0.0.0.0) bind=127.0.0.1;; esac; \
	  cd backend && MSP_TEST_MYSQL_HOST="$${MSP_TEST_MYSQL_HOST:-$$bind}" uv run pytest -q

test-frontend: frontend-deps
	cd frontend && $(NODE_BIN)/vitest run

test: lint test-backend test-frontend  ## the full cumulative regression suite

migrate:  ## upgrade the schema and apply role grants (uses MIGRATOR_DATABASE_URL)
	$(SELECTOR) migrate up
	$(SELECTOR) db-grants

ingest-dev: migrate  ## dev data: committed CMS sample fixtures (Maricopa, AZ) + dev ZIP→county rows, no network
	$(SELECTOR) ingest --year 2027 --fixtures
	$(SELECTOR) hud load-file tests/fixtures/hud/zip_county_dev.csv --year 2026 --quarter 2
	$(SELECTOR) directories sync --year 2027 --seed-only

ingest: migrate  ## real CMS 2027 ingest (downloads ~hundreds of MB the first time)
	$(SELECTOR) ingest --year 2027
	$(SELECTOR) directories sync --year 2027 --seed-only

directories-sync:  ## map carriers' public provider directories (UHC, Humana) to 2027 plans (network, ~1 req/s/host)
	$(SELECTOR) directories sync --year 2027

purge:  ## retention purge (Saved sessions idle > RETENTION_DAYS, old feedback)
	$(SELECTOR) purge

api-dev:  ## API on the host at http://127.0.0.1:8000 (reload on change)
	cd backend && $(LOAD_ENV) env $(DEV_DB) COOKIE_SECURE=false uv run selector ephemeral-flush
	cd backend && $(LOAD_ENV) env $(DEV_DB) COOKIE_SECURE=false \
	  uv run uvicorn --factory selector.api.main:app_factory --host 127.0.0.1 --port 8000 --reload --no-access-log

web-dev:  ## Vite dev server at http://localhost:5173 (proxies /api to :8000)
	cd frontend && npm run dev

# The dev MySQL runs on tmpfs, so after a restart (e.g. `make app-down`, a reboot) it is empty. dev-data then loads the
# committed dev sample data; a database that already holds plan data (dev sample or a real `make ingest`) is untouched.
# The check uses the same connection as `make ingest-dev` (INGEST_DATABASE_URL) and skips Redis, which ingest never uses.
HOST_URL_HINT := Host-side make targets read DATABASE_URL, INGEST_DATABASE_URL, MIGRATOR_DATABASE_URL and REDIS_URL from \
  .env: they must use 127.0.0.1:3307 / 127.0.0.1:6380 (this machine's stack) or the LAN address of the machine whose \
  stack you use (e.g. 192.168.0.216:3307 / :6380, published there with MSP_DB_BIND), or be left out. The names \
  mysql:3306 and redis:6379 only resolve inside containers.
dev-data: stack-up  ## load the dev sample data only if the plan database is empty
	@cd backend && $(LOAD_ENV) env $(DEV_DB) sh -c 'DATABASE_URL="$$INGEST_DATABASE_URL" exec uv run selector check-data --data-only' 2>/dev/null; rc=$$?; \
	  if [ $$rc -eq 3 ]; then \
	    echo "The dev plan database is empty (MySQL runs on tmpfs): loading the dev sample data (make ingest-dev)."; \
	    $(MAKE) -C $(CURDIR) --no-print-directory ingest-dev; \
	  elif [ $$rc -ne 0 ]; then \
	    $(LOAD_ENV) env $(DEV_DB) sh -c 'DATABASE_URL="$$INGEST_DATABASE_URL" exec uv run selector check-data --data-only'; \
	    echo "" >&2; echo "$(HOST_URL_HINT)" >&2; exit 1; \
	  fi

# Only the app services (api, web) are built/recreated; MySQL and Redis are started if needed but never recreated.
app-up: stack-up dev-data  ## API + nginx web UI in Docker on http://$${MSP_WEB_BIND:-127.0.0.1}:$${MSP_WEB_PORT:-8080}
	@$(DEVDB) [ -z "$$DEV_DB_REMOTE" ] || echo "api container uses the dev MySQL/Redis on $$DEV_DB_HOST"; \
	  $(COMPOSE) --profile app up -d --build --wait --no-deps api web || { \
	  echo "" >&2; \
	  echo "ERROR: the API did not become ready. Last API log lines:" >&2; \
	  $(COMPOSE) --profile app logs --tail 15 api >&2; \
	  echo "If it says the plan data is missing: make ingest-dev && make app-up" >&2; \
	  exit 1; }

app-down:
	$(COMPOSE) --profile app down

app-logs:
	$(COMPOSE) --profile app logs -f api web

precommit:  ## run before every proposed commit (gitleaks, forbidden files, linters)
	$(UV) pre-commit run --all-files

build-frontend:
	cd frontend && npm run build

smoke:  ## quick check of a running app (make app-up or api-dev): config, a No-save session and a Maricopa compare
	@$(LOAD_ENV) host="$${MSP_WEB_BIND:-127.0.0.1}"; [ "$$host" != 0.0.0.0 ] || host=127.0.0.1; \
	  bash scripts/smoke.sh "$${SMOKE_URL:-http://$$host:$${MSP_WEB_PORT:-8080}}"

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
