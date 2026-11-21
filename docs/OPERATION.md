# Operation: dev and test data stores

How to point the dev app and the test suite at MySQL and Redis. Design background: DESIGN.md §10 and
[DESIGN-v0.4-ADDENDUM.md A10](design/DESIGN-v0.4-ADDENDUM.md) (Redis is app-local).

## Rules (Thomas, 2026-11-20)

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
