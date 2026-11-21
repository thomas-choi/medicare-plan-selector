# QA Report — medicare-plan-selector v0.5 (WP15, WP16, WP19)

Date: 2026-11-21 · Tester: Hermes agent · Code under test: branch `fix/drug-search` @ `035051f`
Reference task: Thomas's QA assignment of 2026-11-21 ("check CHANGELOG since last QA; review design; report to Claude/Philip; suggest production deployment prep").

## Scope

Per the "For QA" items the coding worker left in `docs/CHANGELOG.md`:

1. Full cumulative regression (`make test`) — WP15 Redis-is-local tests, WP16 No-save enforced
   default (NS1–NS7), WP19 AK/CT mapping (AK1–AK6, incl. Philip's B6.1 additions AK5/AK6).
2. A **real** `make ingest` (all CMS 2027 files, XW3 downloaded) on a **local** test database —
   never the live server (A10.3 ruling).
3. The by-hand No-save check from the WP16 entry (`DEFAULT_SESSION_MODE=saved` must be refused).

## Results — all pass

| Check | Expected | Actual |
|---|---|---|
| `make test` (lint + backend + Vitest) | 424 backend + 45 Vitest, clean | **424 passed + 45 passed, all clean** |
| Real ingest into local `msp_test_qav05` (127.0.0.1:3307) | validation passes | **passed** (5,884 plans; `plan_county` 159,665) |
| Pending counties (`fips_status='pending'`) | 0 | **0** (was AK + CT pending before WP19) |
| Retired counties | 9 Alaska codes | **9** (02030…02280, each cited in overrides) |
| `plan_county` rows using a retired SSA code | 0 | **0** (81 rows removed vs the pre-WP19 load of 159,746) |
| `crosswalk_nber` counties (XW3) | 30 | **30** |
| Connecticut: 8 legacy counties → FIPS 09001–09015 | via overrides | **8 rows, status `override`; 58 plans serve them** |
| Alaska statuses | `crosswalk_nber` 30 + `retired` 9 | **as expected** |
| `DEFAULT_SESSION_MODE=saved` refused with the B2 message | rc != 0 | **"DEFAULT_SESSION_MODE must be nosave (DESIGN v0.5 B2)"** |
| NS1–NS7 (WP16, in the suite) | green | **green** |

Notes:
- One QA-side hiccup (not a code bug): running the scratch ingest by hand requires
  `selector db-grants` after `migrate up` (conftest does this automatically); first ingest
  attempt failed with access denied before grants were applied.
- Scratch DB was dropped after the checks; nothing was written to the live server
  (192.168.0.216 untouched; its `msp` stays at 0006 — see deployment note below).

## Feedback to Claude (coding)

- **WP15/WP16/WP19 verified — QA complete for these packages.** No findings.
- Minor improvement idea: `selector migrate up` + `selector db-grants` could be one command
  (or migrate could apply grants) so a hand-run scratch setup can't end up half-provisioned,
  as happened in this QA round.

## Feedback to Philip (design)

- **B6.1 conditions verified in code and data** (AK5/AK6 both in the green suite; retired codes
  excluded from the picker, not counted as pending, and ingest would fail on a PlanArea row
  using one). No design changes needed from this round.
- Remaining **U** item stands: whether HUD's live API returns CT planning-region codes or legacy
  county codes (both handled in code).

## Production deployment readiness (for CHANGELOG)

QA considers the code **ready for staging deployment**, with these preparations outstanding:

1. **WP21 production stack** (not implemented): prod compose pinning + `DEFAULT_SESSION_MODE`
   hard-pinned to `nosave` server-side (B2 gaps G2/G3), smoke check NS7 against the live app.
2. **Deploy checklist B8** (med.thomas-choi.com) — approval-gated; Thomas's go decision.
3. **Live server migration**: `msp` on 192.168.0.216 is at Alembic `0006`; the prod stack will
   need `0007`/`0008` only when WP14/WP17 land — no action needed for this deploy.
4. **Directory coverage (WP17)**: only Humana + UHC curated today; Aetna needs app registration
   (Q14, Thomas decision); 6 Maricopa carriers have no public directory (badge "can't check").
5. **Legal review (B10/Q9)** before the Nov 25 public launch — Philip owns.
6. **HUD CT verification** (the U item above) before launch week.
7. **WP14 (carrier PDFs) and WP20 (Playwright E2E, NS8)** are open — not blockers for a
   no-LLM-capable soft launch, per the v0.5 plan ordering.
