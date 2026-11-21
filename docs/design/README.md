# Medicare Plan Selector: Design v0.3 + v0.4 and v0.5 addenda

**Status:** v0.3 signed off by Thomas on 2026-11-12, with the no-save addition. **v0.4 addendum (2026-11-19) and v0.5 addendum (2026-11-21): ready for Thomas's sign-off** (not signed off yet).
**Code:** all work is on branch `fix/drug-search` (`df85aba`, pushed); `main` is still `254266a` until Thomas approves the merge (OPEN-QUESTIONS Q12).
**Repo:** https://github.com/thomas-choi/medicare-plan-selector (public).
**Worker brief:** `../CLAUDE-HANDOFF.md`. **Repo rules (R-A, R-B):** `../CONTRIBUTING.md`.

| File | Purpose |
|---|---|
| `DESIGN.md` | Architecture, data sources, MySQL and Redis model, agent and LLM providers, feedback, privacy (including **§8.5 No-save mode**), abuse controls, compliance notes, deployment, repo layout |
| `IMPLEMENTATION-PLAN.md` | MVP vs post-MVP, milestones (MVP Nov 17, cloud Nov 18, Thomas enrolls Nov 24, public Nov 25), work packages WP0–WP23, cumulative regression suite including no-save N1–N9 and NS1–NS8 |
| `DESIGN-v0.4-ADDENDUM.md` | **v0.4 (ready for sign-off):** drug-search fix, doctors/network directory check, dental, pinned Original Medicare + Part D baseline, API changes, app-local Redis, tests on local MySQL only (A10) |
| `DESIGN-v0.5-ADDENDUM.md` | **v0.5 (ready for sign-off):** repo rules R-A/R-B, No-save as a hard default (B2), carrier documents WP14 (B3), dental-use preset (B4), directories for every Maricopa carrier incl. Aetna (B5), AK/CT mapping (B6), Playwright E2E (B7), deploy checklist (B8), ml3090 checks (B9), legal review (B10), API reference (B11) |
| `HUD-API-SETUP.md` | HUD USPS ZIP→county API token setup |
| `OPEN-QUESTIONS.md` | Accepted defaults (Q1–Q11) and proposed resolutions for Q12–Q22 |
| `CHANGES-FROM-v0.1.md`, `CHANGES-FROM-v0.2.md`, `CHANGES-FROM-v0.3.md`, `CHANGES-FROM-v0.4.md` | Revision history |

**Disclaimer:** this is an independent, free comparison tool. It is not a licensed agent or broker and is not affiliated with CMS or Medicare. It gives estimates only. Confirm on https://www.medicare.gov/plan-compare/, at 1-800-MEDICARE, or with SHIP (https://www.shiphelp.org/local-medicare-help).
