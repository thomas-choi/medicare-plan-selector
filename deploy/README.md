# Deploying med.thomas-choi.com

> **Nothing here is run automatically.** Deploying needs Thomas's approval (the Nov 18 cloud deploy included).
> These are the steps for the operator.

Layout on the server: Docker Compose runs MySQL, Redis (no persistence), the API, the nightly purge job and the web
container (SPA + `/api` proxy) from `docker-compose.prod.yml`. The host nginx terminates TLS on `MED_PUBLIC_PORT`
and proxies to the web container on `127.0.0.1:${MSP_WEB_PORT:-8080}`. Only the host nginx is public.

## 1. Server `.env` (repo root, `chmod 600`, never committed)
Start from `.env.example` and change at least:

| Key | Production value |
|---|---|
| `MYSQL_ROOT_PASSWORD`, `REDIS_PASSWORD` | long random values |
| `DATABASE_URL`, `INGEST_DATABASE_URL`, `MIGRATOR_DATABASE_URL` | host-side URLs on `127.0.0.1:3307` with the real role passwords (for `make migrate` / `make ingest`) |
| `COMPOSE_DATABASE_URL` | `mysql+pymysql://msp_api:<api-pw>@mysql:3306/msp` (used by the containers) |
| `COMPOSE_REDIS_URL` | `redis://:<redis-pw>@redis:6379/0` |
| `PROFILE_ENC_KEY` | `python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"` (enables Saved mode) |
| `COOKIE_SECURE` | `true` |
| `ADMIN_GATE_SECRET` | `python3 -c "import secrets;print(secrets.token_hex(32))"` |
| `MAX_SESSIONS_PER_IP_PER_DAY` | `5` (DESIGN §8.2) |
| `LLM_PROVIDER`, `LLM_MODEL`, key | `anthropic` + `ANTHROPIC_API_KEY`, or `xai` + `XAI_API_KEY`; blank = no-LLM mode |
| `LLM_PRICE_IN_PER_MTOK_USD`, `LLM_PRICE_OUT_PER_MTOK_USD` | the model's list prices, so `LLM_DAILY_BUDGET_USD` works |
| `DOCKER_USER`, `IMAGE_TAG` | image names `${DOCKER_USER}/medicare-plan-selector[-web]:${IMAGE_TAG}` |

## 2. Database and roles (first time)
```bash
make prod-config                                  # validates docker-compose.prod.yml against .env
docker compose -f docker-compose.prod.yml up -d mysql redis --wait
set -a; . ./.env; set +a
docker compose -f docker-compose.prod.yml exec -T mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE USER IF NOT EXISTS 'msp_migrator'@'%' IDENTIFIED BY '<migrator-pw>';
CREATE USER IF NOT EXISTS 'msp_ingest'@'%'   IDENTIFIED BY '<ingest-pw>';
CREATE USER IF NOT EXISTS 'msp_api'@'%'      IDENTIFIED BY '<api-pw>';
GRANT ALL PRIVILEGES ON msp.* TO 'msp_migrator'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL
make migrate        # Alembic to head + table-level grants (API: plan tables read-only)
make ingest         # real CMS 2027 data (first run downloads; checks sha256 against sources.lock)
```
Use the same passwords as in the `.env` URLs. Type them into the heredoc yourself; don't paste them into tickets.

## 3. Build and start
```bash
make prod-build     # api + web images
make prod-up        # mysql, redis, api (flushes eph:* on start), purge (nightly), web on 127.0.0.1:8080
make smoke SMOKE_URL=http://127.0.0.1:8080      # needs plan data; uses and erases a throwaway No-save session
```

## 4. Host nginx + TLS
```bash
sudo cp deploy/nginx/ratelimit.conf /etc/nginx/conf.d/msp-ratelimit.conf
sudo htpasswd -c /etc/nginx/med-admin.htpasswd thomas          # apache2-utils
export ADMIN_ALLOW_CIDR=203.0.113.0/24                          # your admin IP range
set -a; . ./.env; set +a
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
- **Logs:** app logs are allowlisted (request id, method, path, status, ms). `docker compose -f docker-compose.prod.yml logs api`.
- **Backups:** back up the `mysql-data` volume (plan data can be re-ingested; Saved sessions are encrypted).
- **Key rotation:** set a new `PROFILE_ENC_KEY` with `PROFILE_KEY_VERSION` + 1 only together with a re-encryption
  job (post-MVP); rotating the key alone makes old Saved sessions unreadable (users just start over).
- **Admin:** `https://med.thomas-choi.com/admin` (feedback list, triage, CSV export of redacted fields). Every admin
  request is recorded in `admin_audit`.
- **Update:** `git pull`, `make prod-build`, `make migrate`, `make prod-up`.
