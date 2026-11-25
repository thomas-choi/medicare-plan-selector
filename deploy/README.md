# Deploying med.thomas-choi.com

> **Nothing here is run automatically.** Deploying needs Thomas's approval (the Nov 18 cloud deploy included).
> These are the steps for the operator.

Layout on the server: MySQL is **DigitalOcean Managed MySQL** (TLS on port 25060, admin user `doadmin`; there is no
root user and no MySQL container). Docker Compose runs Redis (app-local, no persistence), the API, the nightly purge
job and the web container (SPA + `/api` proxy) from `docker-compose.prod.yml`. The host nginx terminates TLS on `MED_PUBLIC_PORT`
and proxies to the web container on `127.0.0.1:${MSP_WEB_PORT:-8080}`. Only the host nginx is public.

## 1. Server `.env.prod` (repo root, `chmod 600`, never committed)
Production reads only `.env.prod`, never the dev `.env`: `cp .env.example .env.prod && chmod 600 .env.prod`, then
change at least the keys below. The `make prod-*` targets pass `--env-file .env.prod` to Compose; when you run
`docker compose -f docker-compose.prod.yml ...` by hand, add `--env-file .env.prod` yourself (without it Compose
fills the `${...}` values from `./.env`). Host-side `make migrate` / `make ingest` take `ENV_FILE=.env.prod`.
Keep no dev `.env` on the server: `selector` also reads `./.env` for any key `.env.prod` leaves out.

| Key | Production value |
|---|---|
| `MSP_DB_CA_FILE` | `./cert/do.ca.crt` (relative to the repo root; an absolute path works too). Download the DO CA certificate from the database's *Connection details*, `mkdir -p cert`, save it as `cert/do.ca.crt`, `chmod 644` (it is public; `cert/` is git-ignored). The app uses it for TLS with certificate and host-name checks, so the URLs need no `?ssl_ca=`. Compose mounts it read-only in the containers at `/run/msp/do.ca.crt` |
| `DATABASE_URL`, `INGEST_DATABASE_URL`, `MIGRATOR_DATABASE_URL` | `mysql+pymysql://<user>:<password>@<do-host>:25060/msp`, any DO database user that can use `msp`. The same user in all three is fine. Optionally use separate users; then `make migrate` gives the API user read-only plan tables. Passwords with `@ : / ? # %` must be URL-encoded (`%40` for `@`). `DATABASE_URL` is used by the containers and host commands; the other two only by `make migrate` / `make ingest` (the containers get them blank) |
| `REDIS_PASSWORD` | long random value. The containers' `REDIS_URL` is built from it (`redis://:<pw>@redis:6379/0`) |
| `REDIS_URL` | unused in production (Redis is not published to the host); leave the template value or blank |
| `PROFILE_ENC_KEY` | `python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"` (enables Saved mode) |
| `DEFAULT_SESSION_MODE` | `nosave`, the only accepted value (DESIGN v0.5 B2). Any other value stops the API; `docker-compose.prod.yml` also pins it to `nosave`. Saved mode is offered only when `PROFILE_ENC_KEY` is set and the user picks it |
| `COOKIE_SECURE` | `true` |
| `ADMIN_GATE_SECRET` | `python3 -c "import secrets;print(secrets.token_hex(32))"` |
| `MAX_SESSIONS_PER_IP_PER_DAY` | `5` (DESIGN §8.2) |
| `LLM_PROVIDER`, `LLM_MODEL`, key | `anthropic` + `ANTHROPIC_API_KEY`, or `xai` + `XAI_API_KEY`; blank = no-LLM mode |
| `LLM_PRICE_IN_PER_MTOK_USD`, `LLM_PRICE_OUT_PER_MTOK_USD` | the model's list prices, so `LLM_DAILY_BUDGET_USD` works |
| `DOCKER_USER`, `IMAGE_TAG` | image names `${DOCKER_USER}/medicare-plan-selector[-web]:${IMAGE_TAG}` |

## 2. Database (first time)
In the DO control panel, on the database cluster:
- **Users & Databases**: add the database `msp`, and the user(s) that the `.env.prod` URLs name (or use an existing one).
- **Settings → Trusted sources**: add this server (droplet or its IP). Use the VPC (private) host name in the URLs
  when the server is in the same VPC.

Then, in the repo root:
```bash
make prod-config                  # validates docker-compose.prod.yml against .env.prod
make migrate ENV_FILE=.env.prod   # creates the tables (Alembic); grants rights to separate ingest/API users, if any and allowed
make ingest ENV_FILE=.env.prod    # real CMS 2027 data (first run downloads; checks sha256 against sources.lock)
make zip-data ENV_FILE=.env.prod HUD_FILE=ZIP_COUNTY_<MMYYYY>.xlsx   # ZIP→county table (or HUD_API_TOKEN, no HUD_FILE)
```
The ZIP→county table is required: with No-save only, the API never fills it by itself, and without it every ZIP
lookup falls back to "pick your state and county" (and the smoke test in `make prod-up` fails). Either download the
latest **ZIP-COUNTY** file from https://www.huduser.gov/portal/datasets/usps_crosswalk.html and pass it as
`HUD_FILE` (the year and quarter come from the file name, e.g. `ZIP_COUNTY_062026.xlsx` = 2026 Q2), or set
`HUD_API_TOKEN` in `.env.prod` ([HUD setup](../docs/design/HUD-API-SETUP.md)) and run it without `HUD_FILE` to load
all states from the HUD API. It commits 1,000 rows at a time and reconnects like `make ingest`; re-run it when HUD
publishes a new quarter.

Nothing here depends on a particular user name or password: every command uses the users in `.env.prod`.
`make ingest` commits at most 1,000 rows per transaction, prints its progress, and reconnects by itself when the
connection stalls or drops (see `docs/OPERATION.md`). If it still stops (network drop, Ctrl+C, failed validation),
the API reports *not ready* for that year until `make ingest ENV_FILE=.env.prod` is run again and passes. A re-run
skips the tables already loaded and continues the one that was cut off.

## 3. Build and start
```bash
make prod-build     # api + web images; one image: make prod-build api; flags after --: make prod-build -- --no-cache
make prod-up        # checks .env.prod, starts redis, api, purge, web (127.0.0.1:8080), waits until healthy, runs the smoke test
```
The web container listens on `127.0.0.1` unless `.env.prod` sets `MSP_WEB_BIND`. For a LAN-only server without the
host nginx, set `MSP_WEB_BIND=0.0.0.0` (or the host's LAN IP) and `COOKIE_SECURE=false`, then open
`http://<host LAN IP>:8080`. That is plain HTTP with no login: trusted networks only. The smoke test follows the
bind address.
`make prod-up` is the whole start: it validates the config, starts every container, waits for the healthchecks
(the API is healthy once Redis answers and the plan data is loaded) and then runs `scripts/smoke.sh` against the web
container with `SMOKE_DATA=real` (a throwaway No-save session, erased at the end; it counts toward that day's
per-IP session limit). In that mode the Maricopa compare must return ranked plans that include H0028_028_0, each
with `src_ref`; the exact golden rank and totals are checked only against the `make ingest-dev` sample data. The
containers take `DATABASE_URL` only from `.env.prod`, never from a variable exported in your shell.

## 4. Host nginx + TLS
```bash
sudo cp deploy/nginx/ratelimit.conf /etc/nginx/conf.d/msp-ratelimit.conf
sudo htpasswd -c /etc/nginx/med-admin.htpasswd thomas          # apache2-utils
export ADMIN_ALLOW_CIDR=203.0.113.0/24                          # your admin IP range
set -a; . ./.env.prod; set +a
envsubst '${MED_PUBLIC_PORT} ${MSP_WEB_PORT} ${ADMIN_GATE_SECRET} ${ADMIN_ALLOW_CIDR}' \
  < deploy/nginx/med.conf.template | sudo tee /etc/nginx/sites-available/med.conf >/dev/null
sudo chmod 600 /etc/nginx/sites-available/med.conf               # contains the admin gate secret
sudo ln -sf /etc/nginx/sites-available/med.conf /etc/nginx/sites-enabled/med.conf
sudo certbot certonly --webroot -w /var/www/letsencrypt -d med.thomas-choi.com
sudo nginx -t && sudo systemctl reload nginx
```
What the template does: HTTP→HTTPS, HSTS and security headers, `limit_req` (30 r/min on `/api`, 6 r/min on
`/api/chat`, `limit_conn` for SSE), an access log with no query strings and IP prefixes only, the client address
overwritten (not appended) in `X-Forwarded-For`, and `/admin` + `/api/admin/` behind IP allowlist + basic auth with
the `X-Admin-Gate` header added only there (stripped everywhere else).

## 5. Operations
- **Retention purge:** the `purge` service runs `selector purge` at start and every 24 h (`PURGE_INTERVAL_S`).
- **No-save wipe:** every API start flushes `eph:*`; Redis has no persistence, so a Redis restart empties it.
- **Readiness:** `GET /api/ready` is 503 (reason + hint) until Redis answers and plan data for `PLAN_YEAR` is
  loaded; the API healthcheck uses it, so `make prod-up` waits for `make ingest` to have run. `/api/health` is
  liveness only.
- **Logs:** app logs are allowlisted (request id, method, path, status, ms). `make prod-logs` (or `docker compose --env-file .env.prod -f docker-compose.prod.yml logs api`).
- **Backups:** DO Managed MySQL takes the backups (check the retention in the control panel); plan data can be
  re-ingested and Saved sessions are encrypted.
- **Key rotation:** set a new `PROFILE_ENC_KEY` with `PROFILE_KEY_VERSION` + 1 only together with a re-encryption
  job (post-MVP); rotating the key alone makes old Saved sessions unreadable (users just start over).
- **Admin:** `https://med.thomas-choi.com/admin` (feedback list, triage, CSV export of redacted fields). Every admin
  request is recorded in `admin_audit`.
- **Update:** `git pull`, `make prod-build`, `make migrate ENV_FILE=.env.prod`, `make prod-up` (includes the smoke test).
