# Changes from v0.4 → v0.5 (ready for Thomas's sign-off, 2026-11-21)

Thomas's assignment of 2026-11-21 (chat): design the outstanding items and clean up the paperwork. Details:
`DESIGN-v0.5-ADDENDUM.md` (sections B1–B13).

| Area | Change |
|---|---|
| Repo rules (B0.1) | R-A: README holds no detailed configuration (it lives in DESIGN, a report or `docs/OPERATION.md`). R-B: every finished task gets a CHANGELOG entry with When / Who / Reference / What. Also in `docs/CONTRIBUTING.md` and `docs/CLAUDE-HANDOFF.md`. |
| No-save default (B2) | Now a hard requirement. Code verified: default everywhere, but `DEFAULT_SESSION_MODE=saved` is accepted, production compose doesn't pin it, the consent screen honours a Saved default, and the smoke test doesn't check. Fixes and tests NS1–NS8 in WP16. |
| Carrier documents (B3) | WP14 fully designed: CMS PBP Section A web addresses for every plan (T1), curated and verified SB/EOC/ANOC PDFs (T2), Plan Finder links (T3); `plan_document` (Alembic `0007`); `selector docs fetch / verify / report` with link-health checks; `GET /api/plans/{plan_key}/documents`; Canvas, side-by-side, export, tool `get_plan_documents`. No numbers from carrier documents. |
| Dental-use preset (B4) | Presets none / preventive / basic / major / dentures; uses PBP b16 visit limits, copays, coinsurance and maximums; coverage-only mode until price assumptions are cited and approved (Q22); never in totals or ranking. WP17. |
| Doctor directories (B5) | All 16 Maricopa 2027 carriers listed from the CMS Landscape with their Provider Directory API status (5 live, 5 need a key incl. Aetna, 6 none or failing); `directories.yaml` spec; `directory_contract` (Alembic `0008`); Aetna registration and client-credentials key handling; per-endpoint breaker and fallback links; coverage check that fails on a missing carrier. WP18. |
| Added to the design (B6–B10) | Alaska/Connecticut county mapping (WP19), Playwright E2E + N9 browser half (WP20), med.thomas-choi.com deploy checklist (WP21, approval-gated), ml3090 A2.3 checks (WP22), legal review before Nov 25 (WP23). |
| API (B11) | New `GET /api/plans/{plan_key}/documents`, `GET /api/admin/coverage`; changed `GET /api/config` (always `nosave`), `GET /api/plans/{plan_key}/benefits` (`dental_use`), `POST /api/compare` (`documents`, `dental_estimate`, new presets), `POST /api/providers/network` (`reason`, `fallback`). |
| Open questions | Q12–Q21 each have a proposed resolution; Q12 (merge to `main`) and Q14 (Aetna registration) need Thomas; new Q22 (dental price source). |
| Paperwork | v0.4 marked ready for sign-off; stale lines fixed; CHANGELOG deduplicated and completed; README trimmed under R-A with configuration moved to `docs/OPERATION.md`. |
