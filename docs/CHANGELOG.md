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

## WP1 — Ingest (2026-11-13)
- `selector ingest --year 2027 [--accept-new] [--offline]`: fetch → `sources.lock` check → parse → normalize →
  delete-and-insert swap for that `plan_year` in one transaction → validate (rolls back on any failure) → `ingest_run`.
- Sources (`sources/2027.yaml`): S1 Landscape, S2 PBP (minimal), S3 monthly Part D (range-read from the 2.3 GB zip;
  pharmacy-network members skipped), XW1 CMS MA State/County Penetration (SSA↔FIPS), XW2 Census 2020 county list.
- **SSA↔FIPS** (decided 2026-11-12): CMS plan data has SSA county codes only. FIPS comes from the CMS penetration
  file plus 47 cited overrides in `sources/ssa_fips_overrides.csv` (CA partial codes, Broomfield, merged VA/SD
  counties, Guam, American Samoa, Northern Mariana Islands), each checked against the Census list. **Alaska and
  Connecticut are `fips_status='pending'`** (UI must say "use Plan Finder"); fix before the public launch.
- **PBP mapping** (approved 2026-11-12): pcp `b7a`, specialist `b7d`, ER `b4a`, urgent care `b4b`, outpatient
  `b9a` (ohs), each with min and max; inpatient `b1a` tier 1 as per-day intervals (`pbp_inpatient_interval`).
- S3 codes from the CMS PUF record layout 2026: phases 0/1/3, days supply 1/2/4 (30/90/60), cost type 0/1/2;
  insulin = lesser of copay and coinsurance. CMS-suppressed Part D plans keep their plan row with
  `part_d_suppressed=1` (3 plans in 2027). Regional PPOs get their MA region's counties.
- Migration `0002`: `county` re-keyed by `ssa_code` (+ `fips`, `fips_status`, `partial`), `plan_county.ssa_code`,
  `pbp_benefit` min/max, `pbp_inpatient_interval`, S3 cost fields, `plan.ma_region_code/pdp_region_code/
  star_note/part_d_suppressed`.
- HUD client (`selector/geo/hud.py`) + `selector hud preload --state XX|All`; cache stores dates, not times.
- Real 2027 ingest on the dev stack: 5,884 plans, 3,279 counties, 159,746 plan-county rows, 963,666 formulary rows,
  579,031 tier-cost rows; golden `H0028_028_0` verified; re-run leaves table checksums unchanged.
- Fixtures: `backend/tests/fixtures/cms/2027/` (≤ 200 rows per file, `MANIFEST.json` with source sha256), cut by
  `scripts/make_cms_fixtures.py`.
- Tests: parser header contracts, normalization, S3 code mapping and unknown-code stop, PBP services/inpatient,
  county statuses, lock mismatch, golden row, idempotent re-run, other-year isolation, rollback on failed
  validation, HUD client, ZIP cache, models↔migrations.

## Config and dev-data fixes (2026-11-17)
- Blank numeric/boolean values in `.env` (e.g. `LLM_PRICE_IN_PER_MTOK_USD=`) now mean "use the default" instead of
  breaking `Settings()`.
- `.env` is read from the repo root from any directory (then `./.env`, then `$MSP_ENV_FILE`); real environment
  variables still win. Host defaults match the dev stack (127.0.0.1:3307 MySQL, 127.0.0.1:6380 Redis).
- `.env.example` now holds working local dev values (host ports); the dev compose `api` service loads `.env` and
  overrides the DB/Redis URLs with the container service names. Image name
  `${DOCKER_USER:-local}/medicare-plan-selector:${IMAGE_TAG:-latest}`, runtime UID/GID as build args.
- `make ingest-dev`: migrate + `selector ingest --year 2027 --fixtures` (committed CMS samples, never touches
  `sources.lock`) + dev ZIP→county rows. `make ingest` for the real download.
- HUD fallback (HUD-API-SETUP.md): `selector hud load-file ZIP_COUNTY_MMYYYY.xlsx|.csv [--state AZ]`, and
  `selector/geo/resolve.py` (cache → HUD API if a token is set → state county picker).
- Tests: blank values, env-file order, HUD file parsing (CSV/XLSX), fixture ingest CLI, ZIP resolution fallbacks.

## WP2 — Cost engine (2026-11-17)
- `selector/cost/`: `part_d.py` (12-month simulation: plan deductible incl. tiers where it doesn't apply, tier
  copay/coinsurance with CMS min/max, $0 after the `part_d_params` OOP threshold, insulin = lesser of copay and
  coinsurance capped at $35/month and outside the deductible, non-formulary at full price outside TrOOP, 30/60/90-day
  and mail order), `medical.py` (MA copays/coinsurance × utilization preset capped at MOOP; Original Medicare =
  Part B deductible + 20% + Part A deductible, no cap), `engine.py` (totals, worst case, filters with dropped
  reasons, neutral score), `params.py` (all assumptions in one public file), `repo.py` (read-only DB loaders).
- Price order: user price → proxy (`drug_price_proxy`, empty until SPUF prices are ingested) → tier price band
  (low/high range + "check Plan Finder").
- Part B premium/deductible are settings with 2026 values as labelled placeholders (S7 TBD); every estimate cites
  them with `src_ref` source `S7`.
- Neutral ranking: weights over total cost, worst case, stars, must-have fit (share of the user's drugs covered);
  unrated plans score stars as neutral (0.5); "no cap" scores as the worst case; ties by `plan_key`.
- Tests: 44 table-driven unit cases (copay generic, deductible crossover, TrOOP mid-year, insulin, non-formulary,
  30/60/90-day and mail, missing price → range, MOOP, zero drugs, rounding, PDP + Part B, carrier-name permutation,
  SNP/path/must-have filters) and golden cost JSON on the Maricopa fixtures, with H0028_028_0 checked by hand.

## WP3 — LLM provider layer, tools, validator, policy, prompts (2026-11-17)
- `selector/agent/providers/`: one `ChatProvider.complete(system, messages, tools)` interface; adapters
  `anthropic` (Messages API tool use), `openai_compat` (Chat Completions function calling, `LLM_BASE_URL`), `xai`
  (the compat adapter with `https://api.x.ai/v1`, `XAI_API_KEY`, `max_completion_tokens`; checked against
  docs.x.ai on 2026-11-17) and `fake` (scripted for tests, rule-based demo for keyless local runs). Plain httpx, so
  tests mock the HTTP layer; no SDK, no network, no keys in tests. Timeouts/429/5xx → `ProviderUnavailable` → the
  optional `LLM_FALLBACK_PROVIDER`; never on validator failure. Blank `LLM_PROVIDER` = no-LLM mode.
- The provider was never picked (due Nov 16): both adapters ship; DESIGN §6.4's `LLM_PROVIDER=anthropic` is the
  documented production default and `.env.example` uses `fake` so a fresh checkout runs without keys.
- `tools.py`: the ten DESIGN §6.2 tools with pydantic argument models (`extra="forbid"`, ≤5 plans), injected
  `ToolContext` (no session id in any schema), every output with `src_ref[]`, `plan_year`, `data_vintage`.
  `lookups.py`: RxNav and NPPES clients (name only, in-memory LRU cache, 1 req/s).
- `validator.py`: dollar amounts, percentages, star ratings and plan IDs must come from tool output (formatting and
  whole-dollar rounding tolerated); `policy.py`: enrollment promises, network claims, medical advice, discouraging
  calls; sanitizer strips HTML/images and off-allowlist links (medicare.gov, cms.gov, shiphelp.org).
- `orchestrator.py`: tool loop (≤6 rounds, ≤4 calls each), user text wrapped as data, one validator correction round
  then a deterministic summary; `budget_check`/`usage_sink` hooks for WP5. `prompts/system_v1.md`,
  `PROMPT_VERSION=v1`. `selector/profile.py`: the intake profile with DESIGN §8.2 limits.
- Tests: provider contract tests (request/response shapes, error classes, key never in errors), tool schema snapshot
  (`tests/fixtures/tool_schemas.json`), no session id / sponsor fields, every tool output carries `src_ref`, fake
  transcript replay (`tests/fixtures/transcripts/`), validator rejects an injected fake premium, provider fallback,
  budget stop, and the red-team set (prompt injection, cross-session, "rank X first", HTML/markdown/link injection,
  over-long input, network claim).

## WP4 — Sessions, No-save mode, API (2026-11-17)
- `SessionStore` with two implementations: `EphemeralSessionStore` (Redis `eph:{sid_hash}:*`, AES-GCM with a
  per-session key that only the cookie holds, sliding idle TTL capped at `EPHEMERAL_MAX_HOURS`, injectable clock)
  and `MySQLSessionStore` (Saved; ZIP/location, drugs, doctors and chat encrypted with `PROFILE_ENC_KEY`).
- Write guard (`before_cursor_execute`) on the API engine: a No-save request that writes a user table or
  `zip_county_cache` raises; only `feedback_counter`/`usage_daily` and the explicit `allow_writes("feedback")`
  team-message opt-in pass.
- Cookie `msp_sid = v1.<n|s>.<sid>[.<key>]` (HttpOnly, SameSite=Lax, Secure per `COOKIE_SECURE`, path `/api`).
- Endpoints: `GET /api/config`, `POST/GET/DELETE /api/session`, `POST /api/session/end` (beacon → grace TTL),
  `PUT /api/profile`, `GET /api/location|counties|drugs|providers`, `POST /api/chat` (SSE: meta, delta, canvas,
  profile, done; validated text is streamed in chunks).
- Allowlist access log (request id, method, path, status, ms) — no bodies, query strings, cookies, IPs or session
  hashes; validation errors never echo input; `httpx` request logging silenced (RxNav URLs carry drug names).
- `selector purge` (nightly retention purge) and delete-my-data (profile, chat, consent log, usage ledger, encrypted
  feedback text, session; recommendation and redacted feedback rows kept unlinked).
- Tests: crypto/cookie, write guard (N2 unit + API engine), N3, N4 (fake clock + real expiry), N5, N7, N8,
  Saved-mode ciphertext, delete-my-data, purge.

## WP5 — Quotas, cost ledger, no-LLM mode (2026-11-17)
- `selector/quotas.py`: Redis counters for turns and tokens per session, new sessions per IP prefix per UTC day
  (HMAC with a random daily salt kept in Redis for 48 h, optional `IP_HASH_SECRET` pepper; /24 and /48 prefixes),
  and the global `LLM_DAILY_BUDGET_USD` (micro-USD from `LLM_PRICE_*`; re-seeded from `usage_daily` if Redis lost it).
- `usage_daily` (all modes, no session/IP linkage) and `usage_ledger` (Saved only; removed by delete-my-data).
- The budget check runs before every model call, so a turn can stop midway (429 `budget`); once spent,
  `/api/config` reports `llm_enabled: false` and `/api/chat` answers 503 `no_llm`.
- `POST /api/compare`: the no-LLM comparison (form → ranked table, top 3, checklist, notes, data vintage) that keeps
  working when chat is off, paused or over quota. Saved mode records `recommendation` rows; their ids go into the
  canvas for the feedback widgets.
- `deploy/nginx/ratelimit.conf`: `limit_req` 30 r/min on `/api`, 6 r/min on `/api/chat`, `limit_conn` for SSE.
- New setting `IP_HASH_SECRET` (optional).

## WP6 — Feedback and admin (2026-11-17)
- `POST /api/feedback`: `recommendation_rating`, `session_outcome`, `general`, `bug`. Saved: linked rows (rating
  anchored to the session's `recommendation` row, by id or plan key), free text → `selector/redact.py` →
  `text_redacted`; raw text AES-GCM encrypted only with "Include my details". No-save: ratings/outcomes only bump
  `feedback_counter` (text dropped); the "Send a message to the team" form (`to_team: true`) stores one redacted row
  with `session_id = NULL`, `mode = 'nosave'` and never raw text. The agent's `record_feedback` tool uses the same
  path.
- Migration `0003`: `feedback.confidence` (outcome card) and `feedback.context_json` (bug page/view state and last
  tool-call ids, never message content; also `enrolled: planned`).
- Redactor: drug lexicon + generic-name stems + the user's own drug/doctor names, "Dr." names, emails, phones,
  dates, ZIPs, NPI-like and long numbers, MBI and SSN patterns.
- Admin API behind `X-Admin-Gate` (constant-time compare; blank `ADMIN_GATE_SECRET` = off): list with filters,
  CSV/JSON export of redacted fields only, triage (`new → accepted → test-added → closed`), summary (thumbs rate,
  stars, outcome distribution, rows by kind/status, LLM usage by mode); every action in `admin_audit`.
- Tests: redactor cases, N1 (row counts + `CHECKSUM TABLE` of every user table unchanged across the full No-save
  flow; counters hold no session/IP/PHI), N9 backend part, Saved rows/opt-in/unlink on delete, agent tool, admin.

## WP7 — Frontend (2026-11-17)
- React SPA (no new dependencies): consent + mode picker (No-save preselected per `DEFAULT_SESSION_MODE`, Saved
  disabled when the server has no `PROFILE_ENC_KEY`, names the LLM provider and the lookup services), header with
  mode badge, "Download comparison", "Feedback", "End session & erase" / "Delete my data"; disclaimer on every page.
- Intake form: ZIP → county (split ZIPs show each county's share; unknown ZIP → state + county picker), drug search
  via RxNav or manual RxCUI, days supply, optional price per fill, doctors (network always "call to confirm"),
  path, utilization, pharmacy, minimum stars, "cover all my drugs". "Compare plans" uses the no-LLM endpoint.
- Chat over SSE (validated text streamed in chunks) with source chips; disabled with a notice in no-LLM mode or
  over quota while the form keeps working.
- Canvas: top-3 cards with 👍/👎, sortable table (dropped plans greyed with the reason), SVG stacked cost chart
  with worst-case markers, side-by-side (2–5 selected plans), checklist; "How we estimate" notes.
- Feedback: outcome card, feedback dialog (No-save: "Send a message to the team" with the storage notice; Saved:
  include-details opt-in). Markdown export built in memory. Safe markdown renderer (React-escaped, no HTML/images,
  links only to medicare.gov, cms.gov, shiphelp.org). `pagehide` → `sendBeacon('/api/session/end')` in No-save.
- State is memory-only (ESLint still bans browser storage). Vitest: disclaimer, consent/mode, intake→compare,
  storage empty, renewed-session notice, no-LLM notice, markdown safety, table/chart/side-by-side, export, SSE
  parser, feedback dialog in both modes.
- `/api/config` now also returns the checklist and the link allowlist.

## WP8 — Deploy artifacts (2026-11-17)
- Web image (`frontend/Dockerfile`, `frontend/nginx.conf`): Node 22 build → unprivileged nginx on :8080 serving the
  SPA (strict CSP, no-store HTML) and proxying `/api` (SSE unbuffered for `/api/chat`). Dev compose `web` service on
  `127.0.0.1:${MSP_WEB_PORT:-8080}`; API healthcheck; API and web containers read-only with tmpfs `/tmp`.
- `docker-compose.prod.yml` (standalone): MySQL on a named volume (localhost-only port for migrate/ingest), Redis
  without persistence and with `REDIS_PASSWORD`, API, nightly `purge` (`purge-loop` entrypoint command), web;
  secrets only from the server `.env`; `COMPOSE_DATABASE_URL`/`COMPOSE_REDIS_URL` required.
- `deploy/nginx/med.conf.template` (TLS, HSTS, security headers, rate limits, privacy access log with IP prefixes and
  no query strings, `X-Forwarded-For` overwritten, `/admin` + `/api/admin/` behind allowlist + basic auth + gate
  header) and `deploy/README.md` (operator runbook). Both nginx configs pass `nginx -t`.
- Makefile: `purge`, `api-dev`, `web-dev`, `app-up/down/logs`, `smoke` (`scripts/smoke.sh`), `prod-*`.
- README: exact test-run steps for a fresh Ubuntu 22.04 machine; `.env.example` finalized (dev-friendly
  `MAX_SESSIONS_PER_IP_PER_DAY=200`, production value 5 noted).

## QA fixes (2026-11-18, qa/QA-REPORT.md)
- #1 `.env.example`: every comment on its own line (Compose `env_file` kept `KEY=   # note` as the value and the API
  container crashed); Settings treats a value starting with `#` as blank; a test parses the file the Compose way.
- #2 Intake: "Add by RxCUI" works without a drug name (label `RxCUI <n>`), Enter submits, inline messages for
  non-numeric, too-long or duplicate input.
- #3 Makefile: frontend tools run from `frontend/node_modules/.bin`; a `frontend-deps` check says to run `npm ci`
  instead of `npx` downloading the unrelated `tsc` package.
- #4 Title: not reproducible in the app (no emoji anywhere in source or build); tests pin a plain-text title.
- #5 `MSP_WEB_BIND` defaults to `127.0.0.1` (blank/unset no longer binds 0.0.0.0); LAN access documented.
- #6 `make app-up` only builds/recreates `api` and `web`; `stack-up` uses `--no-recreate`. New `GET /api/ready` and
  `selector check-data`; healthchecks use readiness, so a missing/empty schema fails loudly with "make ingest-dev".
- Docs: exact test counts, `LLM_PRICE_*` needed for the budget cap, `openai_compat` with the NVIDIA API catalog,
  RxCUI 197361 is amlodipine 5 mg (was mislabelled metformin).
