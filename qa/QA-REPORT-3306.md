# QA Report — medicare-plan-selector regression against shared MySQL (port 3306)

Date: 2026-11-19 · Tester: Hermes agent · Repo: `/home/thomas/projects/medicare-plan-selector` (code under test: `feat/v0.4` at `7c062c4`, WP9–WP13; the original header said `feat/mvp-wp2-8` / `10ee306`, which has
no v0.4 code. Corrected 2026-11-20.)

## Scope

Cumulative regression suite (`backend/uv run pytest`) pointed at the shared dev/QA MySQL
server instead of the repo-local Docker stack:

- **Shared server:** `mysql-srbaw` container, `mysql:8.4`, bound to `192.168.0.216:3306`
  (Docker on Big-Data drive, stack under `/home/thomas/srbaw-mysql-backup/`).
- **Credentials:** real `MSP_TEST_MIGRATOR_PASSWORD` / `MSP_TEST_INGEST_PASSWORD` /
  `MSP_TEST_API_PASSWORD` / `MSP_TEST_REDIS_PASSWORD` injected via `MSP_TEST_*` env vars
  (parsed from `/home/thomas/.secrets/medicare-plan-selector.env`, never printed).
- **What the suite covers:** schema migrations, CMS 2027 ingest fixtures, cost engine and API integration,
  2027 Medicare parameters (WP10), Original Medicare + Part D baseline (WP11), dental (WP12), doctors (WP13),
  drug search (WP9), zip cache, readiness checks, quotas, feedback, saved sessions, and the No-save suite
  (DESIGN §8.5). (Work-package labels corrected 2026-11-20.)

## Results

| Suite | Result |
|---|---|
| Backend (pytest, against 3306) | **340 passed, 39 failed, 8 errors** |
| Backend (pytest, repo-local stack, `make test`) | 387 passed, 0 failed (re-run 2026-11-20 on the same code; the original 305 was from an older run) |
| Frontend (Vitest, `make test`) | 43 passed, 0 failed (re-run 2026-11-20; the original 27 was from an older run) |
| Lint (ruff, mypy, tsc, eslint, prettier) | all clean |

## Analysis

**All 340 passing tests are the MySQL-backed ones** — migrations, ingest, cost engine,
API integration, dental/drugs/doctors, zip cache, readiness data checks, quotas, feedback,
saved sessions. The shared 3306 server works correctly for the v0.4 WP9–WP13 code.

**All 39 failures + 8 errors are Redis-related, not MySQL-related.** The shared server has
no Redis on `192.168.0.216:6380`, so:

- `tests/nosave/*` (ephemeral store, session TTL, restart-flush, ciphertext) fail;
- `readiness.py` reports `redis_unavailable (plan year 2027)`;
- quota / feedback / saved-session tests error on `redis.exceptions.ConnectionError`.

These same tests pass when run against the repo-local stack (which has its own Redis).

## Conclusion

- WP9–WP13 code is verified against the shared MySQL: no regressions.
- The only gap: the tests looked for Redis on the MySQL host. No-save (DESIGN §8.5), quotas and readiness need Redis.

## Recommended next step (superseded)

> **Not adopted.** Thomas decided on 2026-11-20 that Redis stays app-local (DESIGN-v0.4-ADDENDUM A10); the shared
> server provides MySQL only. Original recommendation, kept for the record:

Stand up a Redis on `192.168.0.216:6380` (password-protected, `restart:always`, compose
file in the same Big-Data stack dir) alongside the shared MySQL, then re-run the full
backend suite against the shared server to confirm 100% green including the No-save tests.

## Follow-up 2026-11-20 (Claude, WP15)

- **Root cause:** `backend/tests/conftest.py` built `REDIS_URL` from `MSP_TEST_MYSQL_HOST`, so pointing MySQL at
  `192.168.0.216` also sent Redis there. Fixed in WP15 (`a3ce1d1`): Redis comes from `MSP_TEST_REDIS_URL` or
  `MSP_TEST_REDIS_HOST` (default `127.0.0.1`), never from the MySQL host. `MSP_TEST_REDIS_PASSWORD` is the
  **local** Redis password: filling it from the shared server's secrets file breaks the local Redis login.
- **`make lint` failed** on this round's `conftest.py` change (3 × ruff E501); fixed in `a3ce1d1`.
- **Re-run from ml3090 (192.168.0.212)**, `MSP_TEST_MYSQL_HOST=192.168.0.216 MSP_MYSQL_PORT=3306`, local Redis:
  304 passed, 89 errors, **0 Redis errors**. Every error is
  `Access denied for user 'msp_migrator'@'192.168.0.212'`: ml3090 only has `msp_dev_*@192.168.0.212` accounts on
  that server, and `msp_dev_migrator` has no GRANT OPTION, which the suite needs for its `msp_test_*` databases.
  The 340 MySQL passes in this report therefore used other accounts (from the secrets file above, which is not on
  ml3090).
- **Local stack:** `make test` green (393 backend, 43 Vitest) after WP15.
- **Also in this round's commit:** `sources.lock` gained `last_modified` dates and one file size (no hash changes).

## Ruling 2026-11-20 (Thomas): this test mode is withdrawn

`192.168.0.216:3306` is for live data only; the test suite (which creates and drops databases) uses this machine's
MySQL only. `conftest.py` now refuses a remote `MSP_TEST_MYSQL_HOST`, so a round like this one stops before touching
the server. Equivalent coverage: `make test` on the local stack (green). The dev app still uses `192.168.0.216` for
live data through `.env`. See DESIGN-v0.4-ADDENDUM A10.3, A10.6, A10.8 and `docs/OPERATION.md`.
