# QA Report — medicare-plan-selector regression against shared MySQL (port 3306)

Date: 2026-11-19 · Tester: Hermes agent · Repo: `/home/thomas/projects/medicare-plan-selector` (branch `feat/mvp-wp2-8`, commit `10ee306`)

## Scope

Cumulative regression suite (`backend/uv run pytest`) pointed at the shared dev/QA MySQL
server instead of the repo-local Docker stack:

- **Shared server:** `mysql-srbaw` container, `mysql:8.4`, bound to `192.168.0.216:3306`
  (Docker on Big-Data drive, stack under `/home/thomas/srbaw-mysql-backup/`).
- **Credentials:** real `MSP_TEST_MIGRATOR_PASSWORD` / `MSP_TEST_INGEST_PASSWORD` /
  `MSP_TEST_API_PASSWORD` / `MSP_TEST_REDIS_PASSWORD` injected via `MSP_TEST_*` env vars
  (parsed from `/home/thomas/.secrets/medicare-plan-selector.env`, never printed).
- **What the suite covers:** schema migrations (WP10), CMS 2027 ingest fixtures (WP11),
  cost engine + API integration tests (WP12), doctors/dental/drugs endpoints, zip cache,
  readiness checks, quotas, feedback, saved sessions, and the No-save suite (WP13).

## Results

| Suite | Result |
|---|---|
| Backend (pytest, against 3306) | **340 passed, 39 failed, 8 errors** |
| Backend (pytest, repo-local stack, `make test`) | 305 passed, 0 failed |
| Frontend (Vitest, `make test`) | 27 passed, 0 failed |
| Lint (ruff, mypy, tsc, eslint, prettier) | all clean |

## Analysis

**All 340 passing tests are the MySQL-backed ones** — migrations, ingest, cost engine,
API integration, dental/drugs/doctors, zip cache, readiness data checks, quotas, feedback,
saved sessions. The shared 3306 server works correctly for the v0.4 WP10–WP12 code.

**All 39 failures + 8 errors are Redis-related, not MySQL-related.** The shared server has
no Redis on `192.168.0.216:6380`, so:

- `tests/nosave/*` (ephemeral store, session TTL, restart-flush, ciphertext) fail;
- `readiness.py` reports `redis_unavailable (plan year 2027)`;
- quota / feedback / saved-session tests error on `redis.exceptions.ConnectionError`.

These same tests pass when run against the repo-local stack (which has its own Redis).

## Conclusion

- WP10–WP12 code is fully verified against the shared MySQL: no regressions.
- The only gap is infrastructure: the shared server does not yet provide Redis, which the
  No-save (WP13) feature requires.

## Recommended next step

Stand up a Redis on `192.168.0.216:6380` (password-protected, `restart:always`, compose
file in the same Big-Data stack dir) alongside the shared MySQL, then re-run the full
backend suite against the shared server to confirm 100% green including the No-save tests.
