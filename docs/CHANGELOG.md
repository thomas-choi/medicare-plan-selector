# Changelog

One entry per work package on `feat/mvp`. Dates are MST (America/Phoenix).

## WP0 — Scaffold (2026-11-12)
- Backend: `backend/` uv project (Python 3.13), FastAPI app factory with `/api/health`, settings for every
  `.env` key, SQLAlchemy Core schema for all DESIGN §5 tables, Alembic baseline `0001`, `selector` CLI
  (`migrate`, `db-grants`, `ephemeral-flush`), Dockerfile + entrypoint (no core dumps, startup flush of `eph:*`).
- Roles: `msp_migrator` (DDL), `msp_ingest` (plan tables RW), `msp_api` (plan RO, user tables RW).
- Compose dev/test stack: `mysql:8.4` on 127.0.0.1:3307, `redis:7.4` on 127.0.0.1:6380 with `--save ""`,
  `--appendonly no`, tmpfs `/data`, password, `volatile-ttl`.
- Frontend: React 18 + TypeScript + Vite skeleton with the DESIGN disclaimer; ESLint bans browser storage APIs.
- Hygiene: `.pre-commit-config.yaml` (gitleaks, forbidden-files hook, ruff, mypy, eslint, prettier), `.gitignore`
  guards, `.env.example`, `docs/SECURITY.md`, `docs/CONTRIBUTING.md`, `docs/DATA-SOURCES.md`, CI workflow, `Makefile`.
- Tests: config defaults, Alembic up/down/up, `plan_year`-first keys, no sponsor fields, API role read-only on plan
  tables, forbidden-files hook, startup flush, **N6**, disclaimer render.
- Deviations from design text (approved 2026-11-12): Python 3.13 and MySQL 8.4 instead of 3.12 / MySQL 8; new docs
  in `docs/` instead of the repo root. Column renames for MySQL reserved words: `ingest_run.rows` → `row_count`,
  `recommendation.rank` → `rank_pos`. `chat_msg` and `feedback` gained `key_version` for key rotation.
  `zip_county_cache.fetched_at` is a DATE (day granularity).
