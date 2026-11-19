# QA Report — medicare-plan-selector (feat/mvp-wp2-8)

Date: 2026-11-18 · Tester: QA agent · Scope: README test-run path, `make test`, Docker Compose E2E, exploratory UI testing of http://127.0.0.1:8080

## Executive summary

6 issues found: 2 High, 3 Medium, 1 Low. All documented flows work end-to-end once the `.env`
blocking bug is worked around. Evidence in `qa/screenshots/`.

| # | Severity | Category | Title |
|---|----------|----------|-------|
| 1 | High | Functional / Deploy | `.env.example` inline comments crash the API container on a fresh setup |
| 2 | High | Functional | "Add by RxCUI" is unusable without a drug name — documented offline path broken |
| 3 | Medium | Robustness | `npx tsc` in Makefile lint installs a bogus package when `frontend/node_modules` is absent |
| 4 | Low | Content | Browser tab title contains a horse emoji ("🐴 Medicare Plan Selector") |
| 5 | Medium | UX / Deploy | Web UI not reachable from other hosts (loopback-bound port; fixed with MSP_WEB_BIND) |
| 6 | Medium | UX / Deploy | `make app-up` recreates MySQL and silently wipes the tmpfs dev data |

## Issue 1 — .env.example inline comments break Docker startup (High)

- Where: `.env.example:46,51,52` (`LLM_FALLBACK_PROVIDER`, `LLM_PRICE_IN/OUT_PER_MTOK_USD`); `docker-compose.yml` env_file.
- Steps: fresh clone → `cp .env.example .env` → `make ingest-dev` (host OK) → `make app-up`.
- Expected: README says `.env.example` "works as-is for local testing" → containers start.
- Actual: `msp-api-1` exits 1. Docker Compose does not strip trailing comments, so the blank
  values are passed as e.g. `LLM_PRICE_IN_PER_MTOK_USD="# USD per million input tokens..."` and
  pydantic Settings validation crashes. Host-side commands tolerate it (different dotenv parser),
  which makes the failure look like a container-only problem.
- Workaround applied during testing: strip trailing `# ...` comments from all lines in `.env`,
  then `make app-up` succeeds.
- Fix suggestion: remove inline comments on blank-value lines in `.env.example`, or move the
  comments to their own lines (keep `# ...` only at line start).

## Issue 2 — Add by RxCUI requires a drug name (High)

- Where: `frontend/src/Intake.tsx:177` — `disabled={!manualRx || drugQ.trim().length < 2}`.
- Steps: intake screen → enter RxCUI `197361` in the RxCUI field (leave Drug name empty) → button stays disabled.
- Expected: README advertises "the RxCUI field works offline" as the no-internet drug entry path.
- Actual: the button is also gated on the *drug name* field having ≥ 2 chars, so RxCUI-only entry
  is impossible. Clicking does nothing and there is no error message.
- Verified: with "metformin" also typed in the Drug name box, the button enables and the drug
  chip is added correctly (30/60/90-day options work).

## Issue 3 — `npx tsc` resolution hazard in lint (Medium)

- Where: `Makefile:33` — `cd frontend && npx tsc --noEmit ...`.
- Steps: fresh machine, run `make test` before `npm ci`.
- Actual: npx downloads the deprecated junk package `tsc@2.0.4` ("This is not the tsc command you
  are looking for") and lint fails, aborting the whole `make test` gate with a confusing error.
- Fix suggestion: `npx --no-install tsc ...` (fails fast with a clear message) or call
  `./node_modules/.bin/tsc`, or have `test` depend on an install step.

## Issue 4 — Title emoji (Low)

`document.title` is "🐴 Medicare Plan Selector". Almost certainly unintended (horse emoji).

## Verified working (no issues found)

- `make test` full gate after `npm ci`: ruff/mypy/tsc/eslint/prettier clean, 283 backend tests,
  20 Vitest tests (README says "~290/~20" — counts are close, drift is cosmetic).
- `docker compose config` valid; 5 containers healthy on the dev compose (`docker-compose.yml`).
- `make ingest-dev`, `make smoke`: all steps pass (ZIP lookup, split-county, golden H0028_028_0
  row, chat SSE, erase).
- UI flow: consent (No-save) → ZIP 85004 → county auto-select → drug add → Compare plans
  (ranked table, badges, "Covers 1 of 1 drugs") → chat "Explain H0028_028_0" with source
  citations → Cost chart (stacked bars render correctly) → Side-by-side table (full rows incl.
  deductibles/caps) → Checklist → Download comparison → End session & erase ("Session ended.
  Everything was erased.").
- Split-county ZIP 85142 shows Maricopa 62% / Pinal 38% picker as documented.
- Saved mode correctly disabled when `PROFILE_ENC_KEY` blank; admin API correctly 404 when
  `ADMIN_GATE_SECRET` blank (matches README).
- No console errors (`window.__qa_errors` hook) across all flows.
- Unknown route falls back to the consent screen (SPA default; acceptable).
- Local MySQL at 127.0.0.1:3306 (mysql-srbaw) is not touched: dev compose uses 3307/6380 on
  tmpfs as documented.

## Issue 5 — Web UI not reachable from other hosts (Medium, UX/Deploy)

- Where: `docker-compose.yml` web service, `ports: "127.0.0.1:${MSP_WEB_PORT}:8080"`.
- Symptom: from another machine, `http://192.168.0.216:8080/` returns `ERR_CONNECTION_REFUSED`
  because every dev port (MySQL, Redis, API, web) is loopback-bound. README documents remote
  access via SSH tunnel only, so this is by design, but it surprised the user.
- Fix applied during QA: `MSP_WEB_BIND` env var added to the web service (default keeps
  loopback-only); `.env` sets `MSP_WEB_BIND=192.168.0.216`. Verified: HTTP 200 via both
  `127.0.0.1:8080` and `192.168.0.216:8080`. MySQL/Redis/API stay loopback-only.
- Note for `.env.example`: an empty `MSP_WEB_BIND` binds 0.0.0.0 (docker compose semantics) —
  documented in `.env.example`; production uses nginx in front, unaffected.

## Issue 6 — `make app-up` wipes dev data when it recreates MySQL (Medium)

- Where: `Makefile:70` — `app-up` runs `compose --profile app up -d --build --wait`, which
  recreates *every* service in the compose file, including MySQL, whenever the compose file (or
  any part of it) changes. MySQL runs on tmpfs, so recreation erases the schema, fixtures and
  ZIP-county rows.
- Symptom observed: after a compose edit + `make app-up`, the app returned
  "The service is unavailable right now" on every page; the API log showed
  `1044 Access denied for user 'msp_api'@'%' to database 'msp'` (empty database, no grants).
- Workaround/fix used: `make ingest-dev && make app-up` (documented flow, but nothing tells the
  user that a compose change implies an ingest re-run).
- Suggestion: scope `app-up` to the app profile only (`up -d --build --wait api web`, or add a
  `--no-recreate`-style guard for mysql/redis), or have the API healthcheck fail on a missing
  schema so the outage is loud rather than silent.

## Real-LLM QA (openai_compat → NVIDIA, added 2026-11-18)

- Config in `.env` / secrets file (`/home/thomas/.secrets/medicare-plan-selector.env`):
  `LLM_PROVIDER=openai_compat`, `LLM_BASE_URL=https://integrate.api.nvidia.com/v1`,
  `LLM_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b`, `OPENAI_COMPAT_API_KEY=<nvapi key>`.
- Initial misconfiguration caught by QA: the first model id (`DeepSeek-V4.1-Flash-1017` with
  `api.deepseek.com`) failed — 401 from DeepSeek (key is an `nvapi-` NVIDIA key) and the key's
  model list has no DeepSeek entry. Corrected to the NVIDIA model above per user.
- Verified: `/api/config` shows the provider label; API-level chat SSE returns a normal
  `meta/delta/done` stream with `validation: ok`; UI chat "Compare plans for me" returns a full
  ranked comparison table with source citations, no console errors.
- The budget counters (`LLM_PRICE_*` blank) mean the daily budget cap is not enforced with real
  prices — fine for QA, worth setting for real usage.

## Final environment (verified 2026-11-18)

- `.env` final values confirmed in the running containers: `LLM_PROVIDER=openai_compat`,
  `LLM_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b`,
  `LLM_BASE_URL=https://integrate.api.nvidia.com/v1`, `OPENAI_COMPAT_API_KEY=<set>`,
  `IMAGE_TAG=v1.0.0-dev` (images rebuilt as `local/medicare-plan-selector[-web]:v1.0.0-dev`),
  `APP_UID`/`APP_GID` = `1000` (API container runs as `uid=1000(app)`).
- Post-rebuild re-verification: all 5 containers healthy; session + chat SSE return
  `validation: ok`; live chat replies end-to-end.

## Not tested

- Saved mode (needs `PROFILE_ENC_KEY` set; README optional variation).
- Real CMS ingest (`make ingest`, network-heavy) and drug search via RxNav (offline RxCUI path tested).
- Production compose (`docker-compose.prod.yml`) beyond config validation.
