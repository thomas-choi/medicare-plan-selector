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
