# Implementation Plan v0.3: Medicare Plan Selector

Status: **Signed off by Thomas 2026-11-12 with the no-save addition.**

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
