# Implementation Plan v0.3: Medicare Plan Selector

Status: **Signed off by Thomas 2026-11-12 with the no-save addition** (v0.3 part). The "v0.4 work packages" and "v0.5 work
packages" sections at the end are **ready for Thomas's sign-off** (2026-11-21).

This plan is written for the Claude Code worker.

**Workflow**
1. Philip writes the plan.
2. Thomas signs off.
3. The worker scans the plan, asks Thomas its questions, then codes in Auto mode.
4. Regression tests accumulate from the start, on branch `feat/mvp`.

**Rules**
- No QA or staging environment.
- **The worker never pushes, merges, tags or deploys.** Commits need a separate signal from Philip. Pushing to the public repo and deploying both need Thomas's explicit approval.
- Public repo: **no secrets, no real user data, no raw CMS files** in any commit.

**Schedule** (all times America/Phoenix, MST)
- Now: Thu Nov 12, 3:30 PM
- MVP: **Tue Nov 17**
- Cloud test deploy: **Wed Nov 18**
- Thomas enrolls: **by Tue Nov 24**
- Public launch: **by Wed Nov 25**
- Open Enrollment ends: Mon Dec 7

## MVP scope (cut hard)

| In the MVP (Nov 17) | After the MVP |
|---|---|
| MA and MA-PD plans, plus stand-alone PDPs for the Original Medicare path (premium + drugs + Part B placeholder) | Medigap quotes (manual and CSV), Medigap G and N rules |
| S1 Landscape, S3 formulary, beneficiary cost and insulin files; **minimal PBP**: PCP, specialist, ER, urgent care, inpatient, outpatient | Full PBP (dental, vision, hearing, OTC) and Star measure detail |
| HUD ZIP→county (API with cache); multi-county prompt | Pharmacy network files and preferred-pharmacy lookup |
| Cost engine with price order (user price → 2026 proxy → range) | January 2027 SPUF prices, plan crosswalk year-over-year |
| Agent with tools; `anthropic` and `openai_compat` adapters, plus `fake` for tests | `openai` (if it differs from compat) and `ollama` adapters |
| Chat + canvas: **Table, Side-by-side, Checklist** | Cost chart polish, printable PDF |
| Anonymous sessions, consent (**No-save default** / Save), **ephemeral Redis store + MySQL write guard**, encrypted saved profile, retention purge, delete-my-data, "End session & erase", client-side comparison download | Optional accounts |
| Feedback: per-recommendation thumbs and rating with text, session outcome, general, bug; redactor; **admin list + CSV export** behind nginx basic auth and IP allowlist | Admin aggregates and dashboards, SSO admin login via fin.thomas-choi.com:8443, triage workflow UI |
| Quotas, nginx rate limits, global daily LLM budget cap, input limits, output validator, red-team tests | Captcha (Turnstile or hCaptcha), per-IP adaptive limits |
| **No-LLM mode** (form + table) | Accessibility audit (WCAG 2.2 AA pass) |
| Disclaimers, `SECURITY.md`, `CONTRIBUTING.md`, `.env.example`, pre-commit with gitleaks | Code of conduct, contributor docs |

## Timeline

Each milestone's acceptance assumes all earlier tests still pass. Times are MST.

| When | Milestone | Acceptance |
|---|---|---|
| **Thu Nov 12 evening** | Sign-off done (v0.3, with the no-save addition); worker plan-mode Q&A | Questions answered; LICENSE is already GPL-3.0 in the repo (no change) |
| **Fri Nov 13** | **M0 Scaffold + M1 Ingest.** Repo skeleton, Alembic baseline, compose (mysql/**redis (no persistence, tmpfs)**/api/nginx), pre-commit/gitleaks, CI workflow file. Ingest S1, S3 subset, minimal PBP and HUD into MySQL by `plan_year`. | Golden row `2027/H0028_028_0` (Maricopa): Part C $0.00, Part D deductible $325.00, MOOP $6,550.00, stars 4.5, OOP threshold $2,400. A re-run makes no changes. Every MA-PD row maps to a FIPS county. `gitleaks` is clean. |
| **Sat Nov 14** | **M2 Cost engine** | 25+ table-driven cases, listed in the regression suite below |
| **Sun Nov 15** | **M3 Agent + tools + validator + quotas + `SessionStore`** (the `EphemeralSessionStore` is built **first**, because the agent needs a store and the ephemeral one is the simpler of the two) | Tool schema snapshots. Fake-LLM transcript replays. Validator rejects an injected fake premium. Red-team set passes. The budget cap triggers no-LLM mode. **No-save tests N1–N4 pass.** |
| **Mon Nov 16** | **M4 Frontend + consent/mode picker + saved-mode MySQL store/encryption + feedback (counters for No-save) + admin export** | Vitest components. Playwright end-to-end on fixtures: consent → intake → top 3 → thumbs → outcome → delete-my-data, after which no rows remain. Encrypted columns are not plaintext in a DB dump. Logs contain no message bodies (a test greps the log output). **No-save tests N5–N9 pass.** |
| **Tue Nov 17** | **MVP.** Thomas runs his own session on real 2027 data on ml3090 or locally. | Cited top 3 plus a checklist. Any bugs become tests. |
| **Wed Nov 18** | **Cloud test deploy** to `med.thomas-choi.com:<port>` (Thomas approves the deploy) | TLS A-grade headers; rate limits verified with a load script; `/admin` blocked from non-allowlisted IPs; budget cap set |
| Nov 19 – 23 | Testers use it; feedback triage; fixes (each one test-first); post-MVP items as time allows (Medigap manual entry first) | All accepted feedback items have a regression test or a recorded decision |
| **By Tue Nov 24** | **Thomas enrolls** after confirming his finalists on Plan Finder and calling the plans | Outcome recorded with the feedback tool (dogfooding) |
| **Wed Nov 25** | **Public launch** (same deployment; announcement is Thomas's call) | Monitoring: error rate and daily LLM spend checked each day until Dec 7 |
| Nov 26 – Dec 7 | Support window: fixes only, no schema-breaking changes; extra budget headroom for the final week | — |
| Jan 2027+ | CY2027 quarterly SPUF prices, SSO admin, accounts, crosswalk, Provider Directory FHIR (U) | — |

### Fallbacks (no LLM)
- **Trigger:** M3 not green by **Sun Nov 15 at midnight**, or the MVP not usable by **Wed Nov 18**.
  - **Then:** ship the **no-LLM mode** as the product (form → filters → cost table → checklist, with citations). This needs only M1, M2 and part of M4.
- **Trigger:** M1 itself slips.
  - **Then:** Thomas uses the guided conversation here, plus Plan Finder by hand, and still enrolls by Nov 24.

## Work packages

Each package is PR-sized, with tests first. A `docs/CHANGELOG.md` entry is required for each. **Stop and ask Thomas** when a CMS file's shape differs from the design, a PBP field is ambiguous, or a legal or compliance wording choice comes up.

| WP | Scope |
|---|---|
| WP0 | Scaffold: pyproject, Vite, compose, Alembic, pre-commit (gitleaks, ruff, mypy, eslint, prettier), `.gitignore` guards, `SECURITY.md`, `CONTRIBUTING.md`, `.env.example` |
| WP1 | Ingest: fetch, remote zip, manifest/lock, parsers (landscape, SPUF, PBP-min, HUD), normalize, staging→swap, validate |
| WP2 | Cost engine + `part_d_params` |
| WP3 | Provider abstraction (`anthropic`, `openai_compat`, `fake`), orchestrator, tools, validator, policy, prompts (`prompt_version`) |
| WP4 | `SessionStore` interface; **`EphemeralSessionStore`** (Redis, per-session cookie key, sliding TTL, absolute cap, startup flush); **write guard**; `MySQLSessionStore`; consent and mode; AES-GCM crypto; retention purge; delete-my-data; log allowlist |
| WP5 | Quotas, usage ledger, budget cap, nginx rate-limit template, no-LLM mode |
| WP6 | Feedback API, PHI redactor, `feedback_counter` + `usage_daily` (no linkage), the explicit team-message form, admin list and CSV export, admin audit |
| WP7 | Frontend: chat, canvas (table, side-by-side, checklist), feedback widgets, consent, disclaimers, delete |
| WP8 | Deploy: `docker-compose.prod.yml`, nginx template (TLS, headers, limits, `/admin` gate), `deploy/README.md` |

## Regression suite (cumulative; it only grows)
- **Fixtures:**
  - public CMS sample rows (≤ 200 per file, with vintage and sha256);
  - golden cost JSON;
  - fake-LLM transcripts;
  - anonymized feedback cases.
- **Parser contract tests:** header lists match exactly.
- **Migration tests:** Alembic upgrade and downgrade on an empty MySQL (testcontainers, or the compose MySQL service).
- **Cost tests:**
  - copay generic;
  - deductible crossover;
  - TrOOP cap reached mid-year;
  - insulin;
  - non-formulary drug;
  - 30-day vs 90-day supply, and mail order;
  - missing price, which should produce a range;
  - MOOP cap;
  - zero drugs;
  - multi-county ZIP;
  - rounding;
  - PDP + Part B placeholder.
- **Agent tests:**
  - tool JSON-Schema snapshots;
  - every tool output carries `src_ref`;
  - `session_id` cannot be set by the LLM;
  - validator catches invented numbers;
  - neutrality: the ranking doesn't change when carrier names are permuted.
- **Red team:**
  - prompt injection;
  - cross-session access;
  - "rank X first";
  - HTML/markdown/link injection;
  - over-long input;
  - quota exhaustion.
- **Privacy:**
  - encrypted columns hold ciphertext;
  - delete-my-data removes every row;
  - the purge honors `RETENTION_DAYS`;
  - logs contain no bodies;
  - the redactor strips drug names, phone numbers, ZIPs and emails.
- **No-save tests (N1–N9).** They run against the compose MySQL and Redis with the fake LLM provider.
  - **N1, zero-write:** snapshot the row counts and checksums of every user table (`session`, `profile`, `chat_msg`, `recommendation`, `consent_log`, `feedback`, `usage_ledger`), run the full No-save flow (intake → estimate → compare → 👍 → outcome → end), then assert the tables are unchanged. Only `feedback_counter` and `usage_daily` may change, and they must contain no session or IP values.
  - **N2, write guard:** a forced INSERT into `profile` inside a No-save request context raises an error.
  - **N3, end purge:** after `DELETE /api/session`, `SCAN eph:{sid}:*` returns 0 keys and the cookie is cleared.
  - **N4, idle and absolute timeout:** with `EPHEMERAL_IDLE_MINUTES` shortened in the test config or a fake clock, keys expire. Activity extends the idle TTL but not past `EPHEMERAL_MAX_HOURS`.
  - **N5, API restart:** start a session, restart the API, and assert that `eph:*` is empty and the old cookie gets a fresh session.
  - **N6, Redis restart:** `CONFIG GET save` is empty, `appendonly` is `no`, and the data dir contains no `dump.rdb` or `appendonly*` files. After a Redis restart there are 0 keys.
  - **N7, logs:** capture app and nginx logs during the flow and grep for sentinel values (ZIP `99999`, drug `zzfakedrug`, doctor `Dr Sentinel`). Expect 0 hits.
  - **N8, ciphertext:** raw Redis values don't contain the sentinels. Without the cookie key, the values can't be decrypted.
  - **N9, browser (Playwright):** `localStorage` and IndexedDB are empty after intake. Submitting a team message shows the storage notice and creates exactly one `feedback` row with `session_id IS NULL AND mode='nosave'`.
- **Frontend:** Vitest, plus a Playwright happy path and a no-LLM path.
- **Rule:** every accepted bug or feedback item gets a failing test first.

## Definition of done (MVP)
- `make test` is green.
- `docker compose up` serves the app locally.
- A real 2027 ingest validates.
- Thomas's session yields a cited top 3.
- Feedback can be recorded and exported (redacted).
- delete-my-data works.
- No-save tests N1–N9 are green.
- `gitleaks` is clean.
- No PHI appears in logs.

---

## v0.4 work packages (Thomas's test comments 2026-11-19; design in `DESIGN-v0.4-ADDENDUM.md`)

Status (2026-11-21): **WP9–WP13 and WP15 are done** and on branch `fix/drug-search` at `df85aba` (pushed). That branch
contains every other branch (`feat/mvp`, `feat/mvp-wp2-8`, `feat/v0.4`, `qa/v0.4-3306-regression`); it is **not yet
merged into `main`** (`254266a`, OPEN-QUESTIONS Q12, needs Thomas). Tests use this machine's MySQL only;
`192.168.0.216` is live data (addendum A10.3; R6 replaced). **WP14 is not started**; it is redesigned in the v0.5
addendum B3 and listed with the v0.5 work packages below. Last recorded result: `make test` green, 393 backend + 43
Vitest (`a3ce1d1`, 2026-11-20). See `docs/CHANGELOG.md`. Same rules as above: cumulative tests, the worker never
pushes, merges, tags or deploys.

| WP | Scope | Size | Depends on |
|---|---|---|---|
| **WP9** (done) | Drug search: `RxNavClient.find` (exact → ingredient → approximate), ranking, `matched_as`/`how` on `GET /api/drugs`, 4 s/8 s timeouts, 0.1 s spacing; intake states (Searching…, found, fallback, empty, error), Enter searches | S | – |
| **WP10** (done) | 2027 Medicare parameters: `medicare_params(plan_year PK, part_b_premium_cents, part_b_deductible_cents, part_b_coins_pct, part_a_deductible_cents, part_a_day61_cents, part_a_lifetime_cents, snf_day21_cents, medigap_hd_deductible_cents, src_ref)`; Alembic `0004` (`0003` was taken); seeded from `sources/2027.yaml` (values A5.2, cited); `CostParams` reads it; remove "2026 placeholder" notes | S | – |
| **WP11** (done) | Pinned baseline: `cost/baseline.py` (`build_baseline`), `cost/medigap.py` (G, N, HDG rules, premium optional), profile `medigap`, `delta_vs_baseline_cents`; `compare_plans` returns `baseline`; Canvas pins the row and side-by-side column; export includes it | M | WP10 |
| **WP12** (done) | Dental: parser `ingest/parsers/pbp_dental.py` for `pbp_b16_dental.txt`, `plan_dental` table (Alembic `0005`), fixture sample, validation (golden H0028_028_0 = $500/yr shared); `GET /api/plans/{plan_key}/benefits`; tool `get_plan_benefits`; Dental column, side-by-side section, must-haves; optional dental-use preset (not built; now WP17, design v0.5 B4) | M | – |
| **WP13** (done) | Doctors: intake NPI pick via `GET /api/providers` with `must_keep`; `network.py` `DirectoryChecker` (Plan-Net FHIR), `sources/directories.yaml` seed (UHC, Humana first), `selector directories sync`, `insurance_plan_map` (Alembic `0006`); CMS opt-out check for the baseline; `POST /api/providers/network`; tool `check_provider_network`; policy/validator change (listing status only); badges + optional filter/weight | L | WP11 (baseline badge) |
| **WP14** (not started; superseded by the v0.5 row below) | Carrier documents: see "v0.5 work packages" (design v0.5 B3) | M | – |
| **WP15** (done) | Test/dev Redis is app-local (addendum A10). Decouple Redis from the MySQL host in `backend/tests/conftest.py`, `scripts/devdb.sh` and the Makefile (part already in `7c062c4`); document in `.env.example` and `docs/OPERATION.md`, correct `README.md`. `docker-compose.yml` / `docker-compose.prod.yml`: comments only (no functional change required). Readiness (`/api/ready`) is unchanged. Owner: Claude coding worker on ml3090; review: Philip. No push, merge or deploy without Thomas's approval | S | – |

### v0.4 tests (added to the cumulative suite)

| IDs | WP | What |
|---|---|---|
| D1–D16 | WP9 | See addendum A2.5 (implemented: 12 unit, 2 integration, 6 UI incl. the **tamsulosin 0.4 mg capsule → RxCUI 863669** regression) |
| P1–P4 | WP10 | `medicare_params` 2027 row equals A5.2 values; every value has a `src_ref`; MA and baseline rows use $209.40 × 12; no "2026 placeholder" note remains |
| B1 | WP11 | Baseline present on paths `ma`, `original` and `both`, and with zero drugs |
| B2 | WP11 | Baseline PDP = lowest (premium + drug midpoint) among non-dropped PDPs; ties by plan_key (fixture with two equal PDPs) |
| B3 | WP11 | Baseline is never dropped by must-haves; a failed must-have adds a note |
| B4 | WP11 | Golden: Maricopa, medium use, amlodipine + brand drug → baseline medical = $292 + 20% × (allowed − $292); worst case "no limit" |
| B5 | WP11 | Medigap G → medical OOP $292, worst case $292 + premium; N → +$20/office visit, +$50/ER; HDG capped at $3,050 |
| B6 | WP11 | Medigap without a quote → `premium_included=false` and the note; with a quote → premium × 12 in the total |
| B7 | WP11 | Ranking of plans is identical with and without the baseline (baseline `rank=null`) |
| B8 | WP11 | UI: baseline is the first row, has the "Standard" badge, can't be sorted below row 1, appears in side-by-side and export |
| DN1 | WP12 | Parser on the fixture sample: max amounts, periodicity enum, shared comprehensive max, optional supplemental flag |
| DN2 | WP12 | Golden H0028_028_0: preventive $500/yr, comprehensive shares it, dentures 50% coinsurance, src_ref S2 b16 |
| DN3 | WP12 | PDP and baseline rows show "No routine dental"; MA without b16 row → "No dental benefit listed" |
| DN4 | WP12 | Must-have "Includes dental" drops only plans without preventive dental, with reason text |
| DN5 | WP12 | Validator rejects a dental dollar amount not in a tool row |
| P5 | WP13 | NPPES pick stores `{name, npi, must_keep}`; No-save writes nothing (N1 extended) |
| P6 | WP13 | DirectoryChecker on recorded UHC/Humana bundles: listed / not_listed / unknown mapping; unreachable → `unavailable` within 8 s |
| P7 | WP13 | Filter on: drops only `not_listed` must-keep doctors; `unknown`/`unavailable` never dropped |
| P8 | WP13 | Policy: "Dr X is in network" without a `listed` row is rejected; with one it must carry the date and "call the plan" |
| P9 | WP13 | Baseline doctor badge: opt-out list hit → "Opted out of Medicare" |
| P10 | WP13 | Outbound requests carry only NPI and plan IDs (respx asserts no ZIP/drug/session values) |
| CD1–CD4 | WP14 | Kept and extended to CD1–CD11 in "v0.5 tests" below (design v0.5 B3.8) |
| R1 | WP15 | `conftest.py`: `MSP_TEST_REDIS_URL` wins; with only `MSP_TEST_MYSQL_HOST` set, `REDIS_URL` uses host `127.0.0.1` (not the MySQL host) and `MSP_TEST_REDIS_PASSWORD` when set |
| R2 | WP15 | `devdb.sh`: remote MySQL + unset or local `REDIS_URL` → Redis is local, `COMPOSE_REDIS_URL` is not forced to the MySQL host, `DEV_DB_REMOTE=1` |
| R3 | WP15 | `devdb.sh`: explicit remote `REDIS_URL` still means remote Redis (existing `test_devdb_remote_stack_from_env_urls` still passes) |
| R4 | WP15 | `make test` with no `MSP_TEST_*` still uses `local-stack-up` and the local ports; `test_app_up_never_recreates_the_tmpfs_stack` still holds (`--no-recreate`, `test-backend` depends on `local-stack-up`) |
| R5 | WP15 | Existing readiness tests unchanged (`/api/ready` still requires Redis and plan data) |
| R6 | WP15 | `conftest.py` refuses a `MSP_TEST_MYSQL_HOST` that is not this machine (tests create and drop databases; `192.168.0.216` is live data). Replaces the withdrawn "suite green against 192.168.0.216" (Thomas, 2026-11-20) |

---

## v0.5 work packages (Thomas's assignment 2026-11-21; design in `DESIGN-v0.5-ADDENDUM.md`)

Status (2026-11-21): **designed, ready for Thomas's sign-off; nothing implemented.** Owner of every coding package: the
Claude coding worker on ml3090 (Plan mode first, Auto after Thomas approves), **reviewed by Philip**. Same rules as above:
cumulative regression tests, the worker never pushes, merges, tags or deploys, commits only on a signal. Every finished
package gets a `docs/CHANGELOG.md` entry under rule R-B (When / Who / Reference / What).

**Order** (today is Sat Nov 21; Thomas enrolls by Tue Nov 24; public launch Wed Nov 25):
1. Before the launch: **WP16** → **WP19** → **WP20**, with **WP22** (Thomas on ml3090) and **WP23** (legal) in
   parallel, then **WP21** (deploy, approval-gated) last. Q12 (merge to `main`) must be approved before WP21.
2. As time allows before the launch, otherwise right after: **WP18** (public directories + coverage check; keyed
   carriers after Q14).
3. After Thomas enrolls (Nov 24): **WP17**, then **WP14**. Both are additive (no schema-breaking change), so they fit
   the Nov 26 – Dec 7 support window if Thomas agrees.

| WP | Scope | Owner | Files (main) | Acceptance tests | Size | Depends on |
|---|---|---|---|---|---|---|
| **WP16** | No-save is the default, enforced (B2): `default_session_mode: Literal["nosave"]`; pin `DEFAULT_SESSION_MODE: nosave` in both compose files; Consent always preselects No-save; smoke asserts it; docs | Claude worker; review Philip | `backend/selector/config.py`, `backend/tests/unit/test_config.py`, `docker-compose.yml`, `docker-compose.prod.yml`, `frontend/src/Consent.tsx`, `frontend/src/App.test.tsx`, `scripts/smoke.sh`, `backend/tests/unit/test_dev_tooling.py`, `backend/tests/nosave/test_api_nosave.py`, `.env.example`, `deploy/README.md` | NS1–NS7 (NS8 with WP20); N1–N8 still green | S | – |
| **WP19** | Alaska and Connecticut county mapping (B6): NBER SSA–FIPS crosswalk as `XW2`, CT legacy counties + planning-region mapping, AK boroughs; empty `pending_fips_states` | Claude worker; review Philip | `backend/selector/ingest/parsers/county_xwalk.py`, `backend/selector/ingest/validate.py`, `sources/2027.yaml`, `sources/ssa_fips_overrides.csv`, `sources.lock`, `backend/selector/geo/`, fixtures, `docs/DATA-SOURCES.md` | AK1–AK4 | S–M | – |
| **WP20** | Playwright E2E + browser half of N9 (B7) | Claude worker; review Philip | `frontend/package.json` + lock (`@playwright/test`), `frontend/playwright.config.ts`, `frontend/e2e/*.spec.ts`, `scripts/e2e_db_check.py`, `Makefile` (`e2e`), `.gitignore`, `.github/workflows/ci.yml` (optional job), `docs/OPERATION.md` | E1–E8 (E1 = NS8, E3/E4 = N9) | M | WP16 |
| **WP22** | ml3090 drug-search checks M1–M4 (B9, from A2.3) | Thomas runs on ml3090; Philip records | `qa/ML3090-A2.3.md` (new), `docs/CHANGELOG.md` | M1–M4 recorded with output and date | XS | – |
| **WP23** | Legal review before the Nov 25 launch (B10, Q9) | Thomas engages counsel and decides; Philip prepares the packet | `docs/design/DESIGN.md` §8.4 (outcome), disclaimer/consent text only if counsel asks | Outcome recorded by Mon Nov 24, 5 PM MST, or the invite-only fallback chosen | – | – |
| **WP21** | Cloud deploy to med.thomas-choi.com (B8), **only after Thomas's explicit approvals** (Q12 merge/push, then deploy) | Thomas approves and holds secrets; Philip prepares and reviews; the worker never deploys | `deploy/README.md` (checklist link), `docs/OPERATION.md`, `docs/CHANGELOG.md` | D1–D10 | M | Q12, WP16, WP19, WP20, WP22, WP23 |
| **WP18** | Directories for every Maricopa carrier (B5): `directories.yaml` entries for all 16 parent orgs; `directory_contract` (Alembic `0008`); client-credentials auth (`directory_auth.py`) with `DIRECTORY_<ID>_CLIENT_ID/_SECRET` from `.env`; per-endpoint breaker; fallback links; `selector directories coverage`; `GET /api/admin/coverage`; UI "can't check" links | Claude worker; review Philip; Aetna key from Thomas (Q14) | `sources/directories.yaml`, `backend/selector/network.py`, `backend/selector/directory_auth.py` (new), `backend/selector/directories.py`, `backend/selector/cli.py`, `backend/selector/models.py`, `backend/alembic/versions/0008_*.py`, `backend/selector/api/routes.py`, `backend/selector/api/feedback_routes.py` (admin), `backend/selector/config.py`, `.env.example`, `frontend/src/Canvas.tsx`, recorded bundles under `backend/tests/fixtures/fhir/` | DIR1–DIR11; P6–P10 still green | L | WP13 (done) |
| **WP17** | Dental-use preset (B4): parser adds visit limits, auth/referral; `benefits/dental_use.py`; presets in profile, compare, benefits endpoint and tool; Intake select + Canvas line + side-by-side breakdown; coverage-only mode until Q22 | Claude worker; review Philip | `backend/selector/ingest/parsers/pbp_dental.py`, `backend/selector/benefits/dental_use.py` (new), `backend/selector/profile.py`, `backend/selector/api/routes.py`, `backend/selector/agent/tools.py`, `backend/selector/agent/validator.py`, `sources/2027.yaml` (`dental_use_assumptions`), `frontend/src/Intake.tsx`, `frontend/src/Canvas.tsx`, `frontend/src/exportMd.ts`, b16 fixture | DU1–DU12; DN1–DN5 and B7 still green | M | WP12 (done) |
| **WP14** | Carrier documents (B3): PBP Section A parser (T1), `plan_document` + `carrier_doc_source` (Alembic `0007`), `sources/carrier_documents.yaml`, `selector docs fetch / verify / report`, `GET /api/plans/{plan_key}/documents`, compare `documents[]`, Canvas popover + side-by-side + export, tool `get_plan_documents`, cron/make targets | Claude worker; review Philip | `backend/selector/ingest/parsers/pbp_section_a.py` (new), `backend/selector/documents.py` (new), `backend/selector/docs_fetch.py` (new), `backend/selector/cli.py`, `backend/selector/models.py`, `backend/alembic/versions/0007_*.py`, `backend/selector/api/routes.py`, `backend/selector/agent/tools.py`, `sources/carrier_documents.yaml` (new), `sources/2027.yaml` (Section A member), `frontend/src/Canvas.tsx`, `frontend/src/exportMd.ts`, `Makefile`, `docs/OPERATION.md` | CD1–CD11 | M | after Nov 24 (Q17) |

### v0.5 tests (added to the cumulative suite)

| IDs | WP | Where defined |
|---|---|---|
| NS1–NS8 | WP16 (NS8 in WP20) | design v0.5 B2.5 |
| CD1–CD11 | WP14 | design v0.5 B3.8 |
| DU1–DU12 | WP17 | design v0.5 B4.6 |
| DIR1–DIR11 | WP18 | design v0.5 B5.7 |
| AK1–AK4 | WP19 | design v0.5 B6 |
| E1–E8 | WP20 | design v0.5 B7 |
| D1–D10 (checklist) | WP21 | design v0.5 B8 |
| M1–M4 (operator checks) | WP22 | design v0.5 B9 |
