# Medicare Plan Selector — developer entry points. `make test` is the gate for every work package.
SHELL := /bin/bash
UV := uv run --project backend
COMPOSE := docker compose

.PHONY: help stack-up stack-down lint test test-fast test-backend test-frontend migrate precommit build-frontend

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1

stack-up:  ## MySQL 8.4 (:3307) and Redis 7.4 (:6380, no persistence) for tests
	$(COMPOSE) up -d --wait mysql redis

stack-down:
	$(COMPOSE) down

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
	cd backend && uv run selector migrate up && uv run selector db-grants

precommit:  ## run before every proposed commit (gitleaks, forbidden files, linters)
	$(UV) pre-commit run --all-files

build-frontend:
	cd frontend && npm run build
