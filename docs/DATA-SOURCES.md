# Data sources and attribution

Plan data comes from public files published by the Centers for Medicare & Medicaid Services (CMS), a US Government
agency. This project is **not affiliated with or endorsed by CMS, Medicare or any plan**. Costs are estimates.

| ID | Source | Use |
|---|---|---|
| S1 | CMS Landscape CY2027 (202611) | Plans, premiums, deductibles, MOOP, stars, counties |
| S2 | CMS PBP Benefits 2027 | Minimal medical copays (PCP, specialist, ER, urgent care, inpatient, outpatient) |
| S3 | CMS monthly Part D formulary files CY2027 | Formulary, tiers, beneficiary cost, insulin |
| S4 | CMS quarterly SPUF (CY2026 pricing) | Drug price proxies until CY2027 pricing is published |
| S6 | CMS 2027 Rate Announcement | Part D standard deductible and out-of-pocket threshold |
| S10 | NLM RxNorm API | Drug name → RxCUI |
| S11 | CMS NPPES NPI Registry API | Provider lookup |
| S12 | HUD USPS ZIP crosswalk API | ZIP → county |
| XW1 | CMS MA State/County Penetration (November 2026) | SSA ↔ FIPS county codes (geography columns only) |
| XW2 | US Census Bureau 2020 county FIPS list | Validates the hand-curated `sources/ssa_fips_overrides.csv` |

Full URLs, verification status and sha256 values are in [design/DESIGN.md §3](design/DESIGN.md) and `sources.lock`.

## Rules
- Raw downloads are never committed. They live in the git-ignored `data/` directory.
- Test fixtures under `backend/tests/fixtures/cms/` are small samples (≤ 200 rows per file) recording the source
  file, vintage and sha256.
- The CMS "Terms and Conditions for Use" for the Part D files must be read before the data is shown publicly
  (DESIGN §3, status **U**).
