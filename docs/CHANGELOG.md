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
