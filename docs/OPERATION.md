# Operation: dev and test data stores

How to point the dev app and the test suite at MySQL and Redis. Design background: DESIGN.md §10 and
[DESIGN-v0.4-ADDENDUM.md A10](design/DESIGN-v0.4-ADDENDUM.md) (Redis is app-local).

## Rule

- **Redis is app-local.** It runs in this machine's compose stack (`127.0.0.1:6380` on the host, `redis:6379` inside
  containers), on tmpfs with no persistence. A remote MySQL never implies a remote Redis.
- **MySQL may be local or shared.** Local is the compose MySQL on `127.0.0.1:3307`. Shared is, for example, the dev
  MySQL 8.4 on `192.168.0.216:3306`.
- `/api/ready` is not ready unless both Redis and the plan data answer.

## Layouts

| Layout | MySQL | Redis | How |
|---|---|---|---|
| Local (default) | `127.0.0.1:3307` | `127.0.0.1:6380` | Nothing to set. `make stack-up`, `make test`. |
| Shared MySQL + local Redis | e.g. `192.168.0.216:3306` | `127.0.0.1:6380` | Below. |
| Another machine's whole dev stack | that machine `:3307` | that machine `:6380` | Opt-in only: set a remote host in `REDIS_URL` on purpose. |

## Dev app against a shared MySQL

In `.env` on this machine (placeholder passwords; never commit `.env`):

```bash
DATABASE_URL=mysql+pymysql://msp_api:<api-password>@192.168.0.216:3306/msp
INGEST_DATABASE_URL=mysql+pymysql://msp_ingest:<ingest-password>@192.168.0.216:3306/msp
MIGRATOR_DATABASE_URL=mysql+pymysql://msp_migrator:<migrator-password>@192.168.0.216:3306/msp
REDIS_URL=redis://:dev-redis-pw@127.0.0.1:6380/0   # or leave it out
MSP_DB_BIND=                                       # blank: this machine's Redis stays on loopback
```

`scripts/devdb.sh` sees that MySQL is not this machine (`MSP_DB_HOST` overrides the detection). Then:

- `make stack-up` starts only the local Redis and checks that the shared MySQL answers;
- `make dev-data` / `ingest-dev` / `migrate` work on the shared MySQL;
- `make app-up` gives the api container the shared MySQL URLs (`COMPOSE_*_DATABASE_URL`) and the local Redis
  (`redis:6379`). An explicit `COMPOSE_REDIS_URL` still wins.

## Tests against a shared MySQL

`make test` with no `MSP_TEST_*` variables uses the local stack. To run the backend suite against a shared MySQL
with this machine's Redis:

```bash
export MSP_TEST_MYSQL_HOST=192.168.0.216
export MSP_MYSQL_PORT=3306                      # the compose default is 3307
export MSP_TEST_MIGRATOR_PASSWORD=<migrator-password>
export MSP_TEST_INGEST_PASSWORD=<ingest-password>
export MSP_TEST_API_PASSWORD=<api-password>
make test                                       # starts the local stack; Redis stays 127.0.0.1:6380
```

The tests create and drop throwaway `msp_test_*` databases on that server, and run migrations on `msp`, so the
migrator account needs those rights there. Thomas approved using `192.168.0.216:3306` for dev testing (2026-11-20).

### Test variables

| Variable | Default | Notes |
|---|---|---|
| `MSP_TEST_MYSQL_HOST` | `127.0.0.1` | MySQL only. Never moves Redis. |
| `MSP_MYSQL_PORT` | `3307` | Set `3306` for the shared server. |
| `MSP_TEST_MIGRATOR_PASSWORD`, `MSP_TEST_INGEST_PASSWORD`, `MSP_TEST_API_PASSWORD` | compose dev passwords | Passwords of `msp_migrator`, `msp_ingest`, `msp_api` on that MySQL. |
| `MSP_TEST_REDIS_URL` | unset | Wins when set. |
| `MSP_TEST_REDIS_HOST` | `127.0.0.1` | `make test-backend` sets it to `MSP_DB_BIND` when that publishes the local stack on one LAN address. |
| `MSP_REDIS_PORT` | `6380` | |
| `MSP_TEST_REDIS_PASSWORD` | `dev-redis-pw` | The **local** compose Redis password. Do not copy a shared server's or production password here. |

Tests never read `.env`. The resolution is in `backend/tests/conftest.py` (`mysql_test_url`, `redis_test_url`).

## Sharing this machine's whole dev stack (opt-in)

On the machine with the stack, set `MSP_DB_BIND=<its LAN IP>` in its `.env`, then
`make stack-down && make stack-up && make ingest-dev` (ports bind when containers are created). MySQL `:3307` and
Redis `:6380` then answer on that LAN address only. The dev passwords are public in this repo: trusted LAN only.
On the other host, put that address in the three DB URLs **and** in `REDIS_URL`. Only then is Redis remote.
