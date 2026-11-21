# Changelog

One entry per work package or task. Dates are MST (America/Phoenix). Since 2026-11-21 every entry follows rule R-B
(**When** / **Who** / **Reference** / **What**; see [CONTRIBUTING.md](CONTRIBUTING.md)). Earlier entries keep their
original form. Branch names in headings are where the work was first committed; all of it is now on `fix/drug-search`
(pushed) and waits for the merge into `main` (OPEN-QUESTIONS Q12).

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

## QA fixes (2026-11-19, qa/QA-REPORT-2026-11-19.md)
- #7 Chat: an empty or whitespace-only model answer is a validator rejection ("empty answer"), so the turn retries
  once and then falls back to the deterministic summary instead of storing an empty reply. The chat UI shows "No
  answer came back for this message. Please ask again." for a finished empty reply instead of an endless "…".
- `make app-up` runs the new `make dev-data`, which loads the dev sample data (`ingest-dev`) only when the plan
  database is empty (the tmpfs MySQL after `app-down`/reboot). `selector check-data` exits 3 when only the data is
  missing (1 otherwise) and takes `--data-only` (skip Redis). When the host cannot reach MySQL, `dev-data` says that
  host-side `.env` URLs must use 127.0.0.1:3307/:6380, not the container names `mysql`/`redis`.
- Remote dev stack (coding host ml3090 using ml3060's MySQL/Redis at 192.168.0.216): `MSP_DB_BIND` in
  `docker-compose.yml` publishes MySQL/Redis on a LAN address (default 127.0.0.1). New `scripts/devdb.sh` decides
  from `.env` whether the dev stack is local or remote; when remote, `stack-up` only checks that it answers (with
  instructions for the DB host), and `app-up` gives the api container the same remote URLs (`COMPOSE_*_URL`).
  `make test` always uses the local stack (`local-stack-up`; `MSP_TEST_MYSQL_HOST` follows `MSP_DB_BIND`).

## WP9 — Drug search fix + design v0.4 addendum (2026-11-19, branch `fix/drug-search`, pushed)
- Thomas's ml3090 test: "the drugs search has no response". Reproduced: RxNav `drugs.json` returns nothing for
  "tamsulosin 0.4 mg capsule"; the intake showed nothing for an empty result and Enter submitted the form.
- `RxNavClient.find`: exact → ingredient name → approximate match, ranked (RxCUI 863669 first for the full string);
  `GET /api/drugs` adds `matched_as` and `how`; lookup timeouts 4 s / 8 s; RxNav spacing 0.1 s.
- Intake: Searching… state, found / fallback / empty status line, error alert with the RxCUI hint, Enter searches.
- Tests: `tests/unit/test_drug_search.py`, `tests/integration/test_api_drugs.py`, `Intake.test.tsx` (+6).
- Docs: `docs/design/DESIGN-v0.4-ADDENDUM.md` (doctors, dental, Original Medicare + Part D baseline),
  `CHANGES-FROM-v0.3.md`, WP10–WP14 in `IMPLEMENTATION-PLAN.md`, Q12–Q21 in `OPEN-QUESTIONS.md`.

## Docs — Mermaid data model diagrams in DESIGN.md §5 (2026-11-19, `4b4350b`, `f3347bd`)
- **When:** 2026-11-19 16:52 and 16:55 MST (commit times; entry added 2026-11-21 because it was missing)
- **Who:** not recorded in the commits (git author `thomas-choi`); this entry was added by Philip
- **Reference:** the design's documentation-first rule (Mermaid data-model diagrams); commit messages `4b4350b`, `f3347bd`
- **What:**
  - `4b4350b` `docs/design/DESIGN.md` §5.0: Mermaid data model diagrams (database `msp` → table groups → tables;
    ER diagrams for public plan data and for user, session and operations data, with keys and references).
  - `f3347bd` `docs/design/DESIGN.md`: diagram titles name the database `msp`.

## WP10–WP13 — Design v0.4 (2026-11-19, branch `feat/v0.4`, pushed; merged into `fix/drug-search`)
- **WP10** 2027 Medicare amounts: `medicare_params` (Alembic `0004`), loaded by the ingest from cited values in
  `sources/2027.yaml` (Part B $209.40/month, $292 deductible; Part A $1,776; Medigap HD $3,050; Plan N copays).
  The 2026 Part B placeholder settings (`PART_B_*`) are gone. Golden Maricopa JSON: +$78/yr, ranks unchanged.
- **WP11** Pinned "Original Medicare + Part D (standard)" baseline in every comparison: Part A + B + the
  lowest-cost PDP for the user's drugs, optional Medigap G / N / HDG assumption (premium only from the user's quote),
  never ranked or dropped, `delta_vs_baseline_cents` on every row. UI: first table row with a Standard badge, first
  side-by-side column, export; Medigap inputs in the intake. Prompt `v2`.
- **WP12** Dental from PBP b16: parser, `plan_dental` (Alembic `0005`), validation (every MA plan has a row; golden
  H0028_028_0 $500/yr shared), Dental column and side-by-side services, must-haves "includes dental" / "dental
  maximum at least $X", `GET /api/plans/{plan_key}/benefits`, tool `get_plan_benefits`. Not added to totals (Q16).
- **WP13** Doctors: NPI pick (NPPES) with must-keep; listing status from carriers' public Plan-Net directories
  (`network.py`, `directory_endpoint` + `insurance_plan_map`, Alembic `0006`, `selector directories sync`) and the
  CMS opt-out list for Original Medicare rows; badges by default, optional filter (drops only `not_listed` /
  `opted_out` must-keep doctors) and `doctor_fit` weight (0 by default); `POST /api/providers/network`, tool
  `check_provider_network`; policy accepts a listing claim only with a `listed` tool row, the date and "call the plan".
- Live checks (2026-11-19): real offline 2027 ingest into a scratch schema passes every validation (5,561 dental
  rows); Humana directory sync maps all 4 Humana fixture plans and a 3-doctor check takes 4.1 s; UHC pages take
  12–15 s (sync uses a 90 s timeout and `_elements`).
- Deviations from the addendum: the baseline's "monthly premium" cell is PDP (+ Medigap quote) with "+ Part B"
  under it, like every other row (Part B is a separate line), instead of Part B + PDP; the dental-use cost preset
  (OD-16, optional) and WP14 (carrier PDFs) are not implemented; Humana's NPI search works (0 results = not listed).

## QA — shared-MySQL (3306) regression round (2026-11-19, Hermes agent)
- when: 2026-11-19 ~21:00 MST
- who: Hermes agent
- Reference: Thomas's request to re-run regression after the WP10–WP13 pull, using the shared
  dev/QA MySQL service (192.168.0.216:3306) with live CMS 2027 data; results in `qa/QA-REPORT-3306.md`.
- What:
  - Provisioned DBA access on the shared server: schema `msp`, users `msp_migrator` /
    `msp_ingest` / `msp_api` (and later `msp_dev_*` restricted to ml3090, 192.168.0.212).
  - Applied Alembic migrations 0004–0006 and re-ran the real 2027 ingest on the shared server
    (`plan_dental` 5,561 rows, `medicare_params` 1 row); `sources.lock` updated and committed.
  - Test-code change: `backend/tests/conftest.py` now reads DB/Redis credentials from
    `MSP_TEST_*_PASSWORD` env vars, keeping the committed dev-stack literals as defaults.
  - Ran the full backend suite against 3306: 340 passed / 39 failed / 8 errors — every
    MySQL-backed test green; all failures are Redis-only (no Redis on the shared server).
  - Standard `make test` (local stack) fully green: lint, backend, 43 Vitest tests.
  - Docs: added `qa/QA-REPORT-3306.md`; committed and pushed branch `qa/v0.4-3306-regression`
    (commit `570543a`); repo remote switched from https to SSH.

## Design — Redis is app-local (2026-11-20, branch `fix/drug-search`, pushed as `4c28e19`)
- Hermes QA against shared MySQL at 192.168.0.216:3306: 340 passed, 39 failed, 8 errors, all Redis connection
  failures. Root cause: `backend/tests/conftest.py` built `REDIS_URL` from `MSP_TEST_MYSQL_HOST` and a hard-coded
  dev password; `MSP_TEST_REDIS_PASSWORD` was ignored. `scripts/devdb.sh` also fell back Redis to the MySQL host.
- Thomas: Redis stays with the app/local stack; the shared server is MySQL only. Readiness is unchanged.
- Docs only (no code, Makefile, compose or test changes in this commit): addendum A10, DESIGN.md §10,
  WP15 in `IMPLEMENTATION-PLAN.md` (owner: Claude worker on ml3090, review: Philip).

## WP15 — Redis is app-local in tests and make targets
- **When:** 2026-11-20 20:35 MST
- **Who:** Claude (Claude Opus 5.5, coding worker)
- **Reference:** WP15 in `docs/design/IMPLEMENTATION-PLAN.md`; addendum A10.4–A10.7 in
  `docs/design/DESIGN-v0.4-ADDENDUM.md`; failures in `qa/QA-REPORT-3306.md` (39 failed + 8 errors, all Redis)
- **What:**
  - `backend/tests/conftest.py`: `redis_test_url()` (`MSP_TEST_REDIS_URL`, else `MSP_TEST_REDIS_HOST` default
    `127.0.0.1`, `MSP_REDIS_PORT`, `MSP_TEST_REDIS_PASSWORD`) never uses the MySQL host; `mysql_test_url()` keeps the
    `MSP_TEST_*_PASSWORD` overrides from `570543a` and fixes its three over-long lines (ruff E501, `make lint` failed).
  - `scripts/devdb.sh`: with `REDIS_URL` unset, Redis is `127.0.0.1`, not the MySQL host; `devdb_check_remote` checks
    only what is remote and no longer tells the operator to publish Redis on the MySQL server.
  - `Makefile`: `test-backend` sets `MSP_TEST_REDIS_HOST` on its own (local bind), never from `MSP_TEST_MYSQL_HOST`;
    `HOST_URL_HINT`, `stack-up` and `app-up` text say Redis stays on this machine.
  - Comments only: `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`.
  - New `docs/OPERATION.md` (local vs shared MySQL, app-local Redis, `MSP_TEST_*` table), linked from README.
    README: corrected the "another machine's MySQL/Redis" section and the expected test counts.
  - Tests: R1 `tests/unit/test_test_stores.py` (4), R2 and the `test-backend` recipe in `test_dev_tooling.py` (2).
    R3–R5: existing tests unchanged and green.
  - Result: `make test` green, 393 backend + 43 Vitest. R6 against `192.168.0.216:3306` with local Redis: 304 passed,
    89 errors, **0 Redis errors**; every error is `Access denied for 'msp_migrator'@'192.168.0.212'` (accounts on the
    shared server, see `qa/QA-REPORT-3306.md`).

## Docs — A10 / plan / QA report aligned with the code after WP15
- **When:** 2026-11-20 20:50 MST
- **Who:** Claude (Claude Opus 5.5, coding worker)
- **Reference:** Thomas's 2026-11-20 review request (verify `QA-REPORT-3306.md` and `DESIGN-v0.4-ADDENDUM.md`
  against the code; check `DESIGN.md` and `IMPLEMENTATION-PLAN.md`); addendum A10; WP15 / R6
- **What:**
  - `DESIGN-v0.4-ADDENDUM.md` A10: status (WP15 done in `a3ce1d1`); A10.1 cites `qa/QA-REPORT-3306.md` and records
    that its "Redis on .216" recommendation was not adopted; A10.2 notes what `7c062c4` and `570543a` had already
    changed; A10.4 names the helpers and the `MSP_TEST_*_PASSWORD` variables; A10.5 accepts `7c062c4`'s
    `redis:6379` rewrite of a local `REDIS_URL`; A10.6 adds the approval for `192.168.0.216:3306` and what the suite
    does there; A10.7 fixes the `MSP_TEST_REDIS_PASSWORD` row and adds the three MySQL password rows; A10.8 records
    the results; new **A10.9** (open, Thomas): test accounts the shared server needs for R6.
  - `IMPLEMENTATION-PLAN.md`: v0.4 status (all of WP9–WP13 + WP15 on `fix/drug-search`, `feat/v0.4` fast-forwarded),
    remaining order, WP15 row done, R6 open.
  - `DESIGN.md` §10 and `CHANGES-FROM-v0.3.md`: point to `docs/OPERATION.md` / WP15 done.
  - `qa/QA-REPORT-3306.md`: corrected code-under-test header (`feat/v0.4` @ `7c062c4`, not `10ee306`), WP labels,
    local counts (387 backend / 43 Vitest on that code); recommendation marked superseded; follow-up section with the
    WP15 fix, the lint failure, and the 2026-11-20 re-run (0 Redis errors, 89 MySQL access-denied).

## Tests use this machine's MySQL only; 192.168.0.216 is live data
- **When:** 2026-11-20 20:58 MST
- **Who:** Claude (Claude Opus 5.5, coding worker)
- **Reference:** Thomas's 2026-11-20 ruling ("MySQL at 192.168.0.216 is for live data only; use local MySQL when the
  database can be thrown away and dropped"); addendum A10.3 / A10.6 / A10.8 / A10.9; IMPLEMENTATION-PLAN R6;
  `qa/QA-REPORT-3306.md`
- **What:**
  - `backend/tests/conftest.py`: `mysql_host_is_local()` + `pytest_configure` guard: pytest stops with a clear
    message when `MSP_TEST_MYSQL_HOST` is not this machine (loopback, its name, or one of its own addresses such as
    `MSP_DB_BIND`). Test: `test_tests_refuse_a_remote_mysql`.
  - Addendum A10: rule "tests use this machine's MySQL only" (A10.3, diagram); shared-MySQL test mode withdrawn and
    A10.6 rewritten as tests (local) + dev app on live data (`msp_dev_*`, never `make ingest-dev` there); A10.7
    rows; A10.8 acceptance and results; A10.9 (shared-server test accounts) withdrawn.
  - `IMPLEMENTATION-PLAN.md`: status, remaining order, WP15 done, R6 replaced by "conftest refuses a remote MySQL".
  - `DESIGN.md` §10, `design/README.md`, `CHANGES-FROM-v0.3.md`, `docs/OPERATION.md` (rewritten),
    README correction, `.env.example` and Makefile comments: same rule.
  - `qa/QA-REPORT-3306.md`: ruling section (this test mode is withdrawn).
  - Live server check after the earlier probe/run: only `msp` exists, still at `0006`; nothing left behind.

## Design v0.5 — outstanding items, repo rules and paperwork cleanup
- **When:** 2026-11-21 01:00 MST
- **Who:** Philip (team lead and architect)
- **Reference:** Thomas's task assignment of 2026-11-21 (chat): "Design/Plan to add WP14, no-save is default,
  Dental-use preset, add doctor directory including Aetna, all carriers in Maricopa must in, try all Q12–Q21 …
  cleanup the paperwork", plus his two repo rules. Source items: `docs/design/OPEN-QUESTIONS.md` Q9, Q10, Q12–Q21;
  `docs/design/IMPLEMENTATION-PLAN.md` WP12 (dental-use preset), WP14, N9, M4/Nov 18 milestones;
  `docs/design/DESIGN-v0.4-ADDENDUM.md` A2.3, A3.2 (Aetna), A4.4 (OD-16), A4.5 (WP14), A7, A8, A9;
  `sources/2027.yaml` `pending_fips_states`.
- **What:**
  - **Repo rules R-A / R-B** recorded in `docs/design/DESIGN-v0.5-ADDENDUM.md` B0.1, `docs/CONTRIBUTING.md` (new
    "Repository rules" section) and `docs/CLAUDE-HANDOFF.md` (new §0; README rule aligned with R-A).
  - **New `docs/design/DESIGN-v0.5-ADDENDUM.md`** (B0–B13, 12 Mermaid diagrams, all rendered with mmdc):
    - B2 No-save default as a hard requirement: code verified; gaps G1–G5 (env accepts `saved`, prod compose not
      pinned, consent honours a Saved default, smoke doesn't check, deploy docs silent); tests NS1–NS8.
    - B3 WP14 carrier documents: URL tiers (PBP Section A, curated verified PDFs, Plan Finder), `plan_document` ER
      (Alembic `0007`), `selector docs fetch / verify / report` with link-health checks, API, UI, tool; no numbers from
      carrier documents.
    - B4 dental-use preset (OD-16): five presets, PBP b16 visit limits/copays/coinsurance/maximums, coverage-only mode
      until a cited price source is approved (Q22).
    - B5 directories: all 16 Maricopa 2027 parent organizations from the CMS Landscape with each one's Provider
      Directory API status checked 2026-11-21 (5 live, 5 need a key incl. Aetna, 6 none/broken); `directories.yaml`
      spec; `directory_contract` ER (Alembic `0008`); Aetna registration and key handling; breaker/fallback; coverage
      check.
    - B6 Alaska/Connecticut county mapping; B7 Playwright E2E + N9 browser half; B8 med.thomas-choi.com deploy
      checklist (approval-gated); B9 ml3090 A2.3 checks; B10 Q9 legal review before Nov 25; B11 API reference; B12
      sources S18–S28; B13 work-package index.
  - `docs/design/IMPLEMENTATION-PLAN.md`: header and v0.4 status line made accurate (done, on `fix/drug-search`, not
    merged to `main`); "(done, local)" labels fixed; WP12/WP14 rows point to v0.5; new "v0.5 work packages" section
    (WP14, WP16–WP23 with owner, files, acceptance tests, order) and the v0.5 test index.
  - `docs/design/OPEN-QUESTIONS.md`: Q12–Q21 each with a resolution, status and rationale/research (Q12 is now "merge
    `fix/drug-search` into `main`"; Q12 and Q14 need Thomas); new Q22; status notes for Q9 and Q10.
  - `docs/design/DESIGN-v0.4-ADDENDUM.md`: status "Ready for Thomas's sign-off"; base line fixed (written against
    `feat/mvp-wp2-8` `10ee306`, now all on `fix/drug-search` `df85aba`); A1 changelog rows (WP15 done, 2026-11-21
    row); A7 says WP15 is done; A8 Q12 targets `main`; A9 S14 dataset id recorded; pointers from A3.2, A4.4 and A4.5 to
    v0.5; "local branch" wording fixed.
  - `docs/design/DESIGN.md`: status names both addenda; §5.0 lists migrations `0004`–`0008`; §8.1 and §8.5 say
    No-save is fixed (v0.5 B2).
  - `docs/design/README.md`: status (both addenda ready for sign-off, code branch), v0.5 row, file list.
  - `docs/design/CHANGES-FROM-v0.3.md`: status and "fixed locally" wording; new `docs/design/CHANGES-FROM-v0.4.md`.
  - Earlier commit `6b9e62c` (same task): `README.md` trimmed under rule R-A with the configuration moved to
    `docs/OPERATION.md`; `docs/CHANGELOG.md` duplicate QA entry removed, diagram-commit entry added, "local branch"
    wording fixed.
  - No code, compose, Makefile, test, `sources/*.yaml` or `LICENSE` changes. Nothing pushed, merged or tagged.

## WP16 — No-save is the default, enforced
- **When:** 2026-11-21 02:05 MST
- **Who:** Claude (Claude Opus 5.5, coding worker)
- **Reference:** WP16 in `docs/design/IMPLEMENTATION-PLAN.md` § "v0.5 work packages"; design v0.5 B2 (NS-REQ, gaps
  G1–G5, tests NS1–NS7) in `docs/design/DESIGN-v0.5-ADDENDUM.md`; Thomas's chat hand-off of 2026-11-21 ("pick up the
  coding task from `fix/drug-search`")
- **What:**
  - G1 `backend/selector/config.py`: `default_session_mode` is `Literal["nosave"]`; any other value (`saved` too)
    fails `Settings()` with "DEFAULT_SESSION_MODE must be nosave (DESIGN v0.5 B2)", so the API refuses to start.
    Blank still means the default. `SessionMode` (nosave | saved) is unchanged for sessions.
  - G2 `docker-compose.prod.yml`: `DEFAULT_SESSION_MODE: nosave` under `x-app.environment` **and** in the `api`
    service's own `environment` (that map replaces the anchor's, so `api` would otherwise have lost the pin);
    `docker-compose.yml` `api`: same pin. Both win over `.env`.
  - G3 `frontend/src/Consent.tsx`: the radio always starts on No-save; `config.default_mode` is no longer used for
    preselection.
  - G4 `scripts/smoke.sh`: asserts `default_mode == "nosave"`.
  - G5 `.env.example` comment, `deploy/README.md` server `.env` table row and `docs/OPERATION.md` row: "must be
    `nosave`; any other value stops the API".
  - Tests: NS1 `tests/unit/test_config.py` (env and `.env` file `saved` refused with the B2 message; `nosave`/blank
    accepted; the old test that accepted `saved` replaced); NS2/NS3 `tests/unit/test_dev_tooling.py` render both
    compose files with `docker compose config` next to a `.env` that sets `saved` (skip if Docker is missing); NS4
    `tests/nosave/test_api_nosave.py`; NS5/NS6 `frontend/src/App.test.tsx` (forged `default_mode: "saved"` still
    preselects No-save; Start untouched posts `mode: "nosave"`); NS7 `test_dev_tooling.py` drives `smoke.sh`
    against a stub API (fails on `saved`, passes the config step on `nosave`). NS8 comes with WP20 (Playwright).
  - `docs/design/IMPLEMENTATION-PLAN.md`: v0.5 status and WP16 row marked done.
  - Result: `make test` green, **406 backend + 45 Vitest** (was 394 + 43); `pre-commit` passed. N1–N8 still green.
  - For QA: check NS1–NS7 above; by hand, `DEFAULT_SESSION_MODE=saved make api-dev` must stop with the B2 message,
    and `make smoke` against a running app must print `ok  GET /api/config`. Not verified here: the production
    stack on the server (WP21).

## WP19 — Alaska and Connecticut county mapping
- **When:** 2026-11-21 02:15 MST
- **Who:** Claude (Claude Opus 5.5, coding worker)
- **Reference:** WP19 in `docs/design/IMPLEMENTATION-PLAN.md` § "v0.5 work packages"; design v0.5 B6 (tests AK1–AK4)
  in `docs/design/DESIGN-v0.5-ADDENDUM.md`; `sources/2027.yaml` `pending_fips_states` ("fix before public launch",
  2026-11-12)
- **What:**
  - New source **`XW3`** (NBER SSA→FIPS crosswalk 2026; the design calls it "XW2", but that id was already the Census
    county list) in `sources/2027.yaml`, pinned in `sources.lock` (sha256 `8c2c6ec0…2207d`, 172,531 bytes). Used only for
    SSA codes missing from XW1: `county_xwalk.parse_nber()` refuses a missing column or an SSA code with two FIPS.
    Status `crosswalk_nber`.
  - `sources/ssa_fips_overrides.csv`: the 8 Connecticut legacy SSA counties → FIPS 09001–09015 (cited to Census 2020).
    Also 9 **retired** Alaska SSA areas with a blank FIPS (02030, 02040, 02080, 02120, 02201, 02232, 02250, 02261
    Valdez-Cordova, 02280), each with a reason and citation. A blank FIPS in an override means status `retired`; the
    Census check accepts it only with a reason and citation.
  - New `backend/selector/geo/ct_regions.py`: Census CT planning region (09110–09190) → legacy counties, from S27
    (`ct_cou_to_cousub_crosswalk.xlsx`, sha256 `f70c3ce6…c238a`, town counts per county). `geo/resolve.py` maps a
    planning-region FIPS from the cache or the HUD API to its legacy county. When a region spans several, it returns
    them all plus a note, and the existing county picker appears. The state picker hides `retired` areas.
  - `ingest/load.py` reads XW3. `ingest/validate.py`: any county left `pending` outside `pending_fips_states` fails
    the ingest. `sources/2027.yaml`: `pending_fips_states: []`.
  - Real 2027 files (checked offline on this machine, no database write): 3,279 SSA codes → 3,185 crosswalk, 55
    override, 30 crosswalk_nber, 9 retired, **0 pending**. All 30 Alaska FIPS that NBER gives are in Census 2020; every
    override passes the Census check. The 2027 Landscape has Alaska only as "All Counties" PDPs and Connecticut by its
    8 legacy counties.
  - Fixtures: AK/CT rows in `geo.txt` and `census_county.txt` (copied from the real files), new `nber_xwalk.csv`
    (12 real rows), `MANIFEST.json`, `devdata.py` layout. Dev ZIPs 99686 (Chugach), 99573 (Copper River), 06103
    (planning region 09110) and 06510 (09170) in `tests/fixtures/hud/zip_county_dev.csv`.
  - Tests: new `tests/unit/ingest/test_ak_ct_counties.py` (AK1, AK3, AK2 table checks, AK4 spec, NBER parser,
    override check, precedence). `tests/integration/test_ingest.py`: statuses and FIPS after ingest replace the old
    "02013 is pending" assertion; AK4 fails ingest on an unknown SSA code. `tests/integration/test_dev_data.py`: AK2
    (multi-county region → picker and note, single-county region, HUD API path), AK3, picker hides retired areas.
  - Docs: `docs/DATA-SOURCES.md` (XW3, S27, AK/CT note), addendum B6 "Implemented" note listing the differences
    (XW3 name, `retired` status, the CT table in code), `IMPLEMENTATION-PLAN.md` WP19 row and status.
  - Result: `make test` green, **420 backend + 45 Vitest** (was 406 + 45); `pre-commit` passed.
  - For QA: (1) full `make ingest` on a **local** test database with the real files. XW3 downloads once, or use
    `--offline` with `data/raw/2027/XW3/ssa_fips_state_county_2026.csv`. Expect validation to pass with 0 pending.
    Never run this against 192.168.0.216. (2) Unverified (**U**): whether HUD's current API and files return CT
    planning-region codes or legacy county codes; both are handled. (3) Philip to review the `retired` status and
    the XW3 naming (addendum B6 note).


## Design review — WP19 differences accepted (B6.1)
- **When:** 2026-11-21 02:55 MST
- **Who:** Philip (team lead and architect)
- **Reference:** the coding worker's WP19 report to Philip (via Thomas, 2026-11-21), which lists three differences from
  `docs/design/DESIGN-v0.5-ADDENDUM.md` B6; Thomas's instruction to update the design and record the review.
- **What:**
  - `docs/design/DESIGN-v0.5-ADDENDUM.md` B6: the NBER crosswalk is renamed `XW2` → `XW3` (design error; `XW2` is the
    Census county list); new tests AK5 (retired codes) and AK6 (CT table matches the Census file); new subsection
    **B6.1 Changes accepted during WP19** recording the three accepted differences and their conditions.
  - `docs/design/IMPLEMENTATION-PLAN.md` WP19: row updated for `XW3`, `geo/ct_regions.py` and the `retired` status;
    acceptance tests AK1–AK4 → AK1–AK6.
  - `docs/CHANGELOG.md`: this entry.
  - Review message sent to the coding worker (through Thomas), in addition to the items above:
    > Philip's review of the WP19 changes: (1) XW3 is accepted. Rename XW2 to XW3 in DESIGN-v0.5-ADDENDUM B6.
    > (2) The retired status is accepted. Retired codes are excluded from the county picker and ZIP lookups, don't count
    > as pending, and ingest fails if a 2027 Landscape plan still uses one. Cite each retired code in the overrides
    > file, and add a B6 paragraph and a test for it. (3) ct_regions.py in code is accepted. Add a header citing the
    > Census CT county-to-planning-region file with its sha256, and a test comparing the table to that file kept as a
    > fixture. Add a CHANGELOG entry (When/Who/Reference/What). Don't push.
  - Note for the worker: the B6 rename and the B6 paragraph asked for in items (1) and (2) are now done by this
    design commit; the worker still owns the code, the overrides citations, the module header and tests AK5/AK6.
  - Code not reviewed yet: the WP19 code was not on GitHub at review time.

## WP19 follow-up — Philip's B6.1 review conditions (AK5, AK6)
- **When:** 2026-11-21 03:35 MST
- **Who:** Claude (Claude Opus 5.5, coding worker)
- **Reference:** Philip's review in the entry above ("Design review — WP19 differences accepted (B6.1)");
  `docs/design/DESIGN-v0.5-ADDENDUM.md` B6 tests AK5/AK6 and B6.1 items 2 and 3
- **What:**
  - B6.1 item 2, retired codes:
    - `ingest/load.py`: PDP and Regional PPO region expansion now skips `retired` SSA areas. The S3 locator still
      lists all 9 retired Alaska codes in PDP region 34 and MA region 26, so before this they were attached to every
      Alaska PDP.
    - `ingest/validate.py`: the ingest fails with "N plan service-area rows use a retired SSA county: …" when a
      plan's own service area (PBP PlanArea) names a retired code. The plan is never dropped silently.
    - `geo/resolve.py`: the ZIP lookup filters out `retired` explicitly, as well as through their blank FIPS.
    - Real 2027 files checked offline: no PlanArea row uses a retired code, so the real ingest still passes.
    - All 9 retired rows in `sources/ssa_fips_overrides.csv` already carry a reason and citation (checked).
  - B6.1 item 3, Connecticut table:
    - The Census file (S27, sha256 `f70c3ce6…c238a`, 29 KB) is now the fixture
      `backend/tests/fixtures/census/ct_cou_to_cousub_crosswalk.xlsx`.
    - The `geo/ct_regions.py` header already cites the file and its sha256; `docs/DATA-SOURCES.md` S27 now names the
      fixture.
  - Tests:
    - **AK5:** `test_ingest.py` covers the ingest failing on a PlanArea row with 02261, and an Alaska-region PDP
      getting 02013/02063/02066/02270 but not 02261. `test_dev_data.py` covers the picker hiding retired areas
      (renamed AK5), and a stale HUD row with the pre-2019 FIPS 02261 finding no county.
    - **AK6:** `test_ak_ct_counties.py` checks that the fixture's sha256 matches the module header, and that
      `CT_PLANNING_REGIONS` equals the region → legacy county → town counts read from the xlsx.
  - Result: `make test` passes with **424 backend + 45 Vitest** tests (was 420 + 45); `pre-commit` passed.
  - For QA:
    - Run AK5/AK6 as above.
    - Run a real `make ingest` on a **local** test database. Expect the validation to pass, and Alaska PDPs to have
      no retired SSA codes in `plan_county`.
  - Not pushed.
