# Changes from v0.3 → v0.4 (draft)

Thomas tested `feat/mvp-wp2-8` on ml3090 on 2026-11-19 and sent four comments. Details: `DESIGN-v0.4-ADDENDUM.md`.

| Area | Change |
|---|---|
| Drug search (A2) | Root cause found and fixed locally (`fix/drug-search`, `19111e0`): RxNav name search returns nothing for "name + strength + form"; the UI showed nothing for an empty result. Fallbacks (ingredient, approximate), ranking, `matched_as`/`how`, shorter timeouts, visible UI states, Enter searches. 20 new tests. |
| Doctors (A3) | Documented that the Doctor field doesn't affect results today. New NPI pick, carrier Plan-Net directory check (CMS-9115-F public APIs), statuses listed / not listed / can't check, opt-out check for Original Medicare, optional filter and weight, policy change to "listing status only". |
| Dental (A4) | New `plan_dental` from PBP `pbp_b16_dental.txt` (S2), Dental column / side-by-side / must-have / tool. Carrier SB/EOC: optional, robots-respecting link fetcher, no number extraction; CMS stays the source of truth. |
| Baseline (A5) | Pinned, unranked "Original Medicare + Part D (standard)" row on every path: Parts A/B (2027 amounts, now **V**) + lowest-cost PDP for the user's drugs + optional Medigap G / N / HDG with a user-entered premium. |
| Parameters | 2027 Part B $209.40/mo and $292 deductible, Part A $1,776, Medigap HD $3,050 (all **V**); new `medicare_params` table replaces the 2026 placeholders. |
| API (A6) | `GET /api/drugs` adds `matched_as`, `how`; new `POST /api/providers/network`, `GET /api/plans/{plan_key}/benefits`; `POST /api/compare` adds `baseline`, `dental`, `doctors`, `documents`, `delta_vs_baseline_cents`; new tools `check_provider_network`, `get_plan_benefits`. |
| Plan | WP9 (done locally) – WP15, tests D, P, B, DN, CD, R in `IMPLEMENTATION-PLAN.md`. Open decisions Q12–Q21 in `OPEN-QUESTIONS.md`. |
| Test/dev Redis (A10, 2026-11-20) | Redis is app-local. Tests and make targets take Redis settings independently of MySQL (`MSP_TEST_REDIS_URL`, else host/port/password with host default `127.0.0.1`). Supported mode: shared MySQL + local Redis. Implemented in WP15 (`a3ce1d1`); shared-server test accounts open (A10.9). |
