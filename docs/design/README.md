# Medicare Plan Selector: Design v0.3 + v0.4 addendum

**Status:** v0.3 signed off by Thomas on 2026-11-12, with the no-save addition. **v0.4 addendum (2026-11-19) is a draft for sign-off.**
**Repo:** https://github.com/thomas-choi/medicare-plan-selector (public).
**Worker brief:** `../CLAUDE-HANDOFF.md`.

| File | Purpose |
|---|---|
| `DESIGN.md` | Architecture, data sources, MySQL and Redis model, agent and LLM providers, feedback, privacy (including **§8.5 No-save mode**), abuse controls, compliance notes, deployment, repo layout |
| `IMPLEMENTATION-PLAN.md` | MVP vs post-MVP, milestones (MVP Nov 17, cloud Nov 18, Thomas enrolls Nov 24, public Nov 25), work packages, cumulative regression suite including no-save N1–N9 |
| `DESIGN-v0.4-ADDENDUM.md` | **v0.4 draft:** drug-search fix, doctors/network directory check, dental, pinned Original Medicare + Part D baseline, API changes, app-local Redis, tests on local MySQL only (A10) |
| `HUD-API-SETUP.md` | HUD USPS ZIP→county API token setup |
| `OPEN-QUESTIONS.md` | Accepted defaults, which still apply unless Thomas objects |
| `CHANGES-FROM-v0.1.md`, `CHANGES-FROM-v0.2.md`, `CHANGES-FROM-v0.3.md` | Revision history |

**Disclaimer:** this is an independent, free comparison tool. It is not a licensed agent or broker and is not affiliated with CMS or Medicare. It gives estimates only. Confirm on https://www.medicare.gov/plan-compare/, at 1-800-MEDICARE, or with SHIP (https://www.shiphelp.org/local-medicare-help).
