# Open Questions (v0.3 defaults, v0.4 and v0.5 resolutions)

Thomas signed off on v0.2 on 2026-11-12 and added the no-save option. The defaults below **apply unless Thomas objects**. The worker should treat them as decided but should confirm Q1 and Q8 in Plan mode.

| # | Decision | Accepted default | Notes |
|---|---|---|---|
| Q1 | **License** | **GPL-3.0, already in the repo** (`LICENSE` in the initial commit `3ebd2ec`). This replaces v0.2's Apache-2.0 suggestion. | GPL-3.0 does **not** require a hosted service to publish modified source; AGPL-3.0 would. To make hosted forks publish changes, Thomas would switch to AGPL-3.0. Do not change `LICENSE` without his say-so. |
| Q2 | Admin auth | **MVP: nginx basic auth + IP allowlist. Post-MVP: SSO** via fin.thomas-choi.com:8443 (`application.medicare_admin`) | — |
| Q3 | LLM budget | **`LLM_DAILY_BUDGET_USD=10`**, `MAX_TURNS_PER_SESSION=40`, `MAX_SESSIONS_PER_IP_PER_DAY=5` | Over the cap, chat switches to the no-LLM mode. |
| Q4 | Retention (saved mode) | **30 days idle** for profile and chat. **365 days** for redacted feedback. | — |
| Q5 | Port and TLS | **443 if free**, otherwise Thomas picks `MED_PUBLIC_PORT`. Wildcard cert or DNS-01. | Let's Encrypt HTTP-01 needs port 80. |
| Q6 | Analytics | **None** (server-side aggregate counts only) | — |
| Q7 | Captcha | **Off at MVP**, Turnstile-ready | — |
| Q8 | LLM provider and model | **Thomas sets it in `.env`** on the server. The worker uses the fake provider plus one real provider for manual runs. | Named on the consent screen. |
| Q9 | Legal review before the Nov 25 public launch | **Recommended** | DESIGN §8.4 is our reading and unverified. |
| Q10 | **Default session mode** | **`DEFAULT_SESSION_MODE=nosave`** (preselected; users can choose Save) | New in v0.3. |
| Q11 | No-save timers | **`EPHEMERAL_IDLE_MINUTES=30`**, **`EPHEMERAL_MAX_HOURS=4`** | New in v0.3. |

Thomas's own intake for his MVP session:
- ZIP code
- current plan
- doctors he must keep
- drug list

## v0.4 open decisions (2026-11-19, `DESIGN-v0.4-ADDENDUM.md`): resolutions proposed 2026-11-21

Philip worked through every question on 2026-11-21 (Thomas's assignment: "try all Q12–Q21"). "Resolved (proposed)"
means: this is the answer the design and the work packages now follow, **pending Thomas's sign-off**. Where a question
needs Thomas personally, the row says exactly what is needed.

| # | Decision | Resolution | Status | Rationale and research |
|---|---|---|---|---|
| Q12 | ~~Merge `fix/drug-search` into `feat/mvp-wp2-8`~~ → **Merge `fix/drug-search` into `main` and push** | Fast-forward `main` from `254266a` to `fix/drug-search` (`df85aba` plus this docs commit once pushed); no merge commit. Then retire `feat/mvp`, `feat/mvp-wp2-8`, `feat/v0.4` and `qa/v0.4-3306-regression` (all contained in it) only if Thomas wants. | **Needs Thomas:** an explicit "yes, fast-forward main and push" in chat. Nothing is merged or pushed before that. | Checked 2026-11-21: `origin/main` (`254266a`) is an ancestor of `origin/fix/drug-search`, 50 commits ahead, so a fast-forward is possible. `fix/drug-search` already contains every other branch. The deploy (WP21) builds from `main`. |
| Q13 | Doctor effect on results | **Badges only by default**; optional must-have "only plans that list my must-keep doctors" drops only `not_listed` (and `opted_out` for the baseline); `unknown`/`unavailable` never drop; `doctor_fit` weight 0 by default | Resolved (proposed by Philip, pending Thomas sign-off). Implemented in WP13. | Directory data is often stale; with only 44 of 92 Maricopa MA plans checkable today (v0.5 B5.2), a default filter would drop plans unevenly by carrier, which breaks the v0.3 §6.3 neutrality rule. |
| Q14 | Register apps with carriers whose directory needs a key (Aetna first) | **Yes for Aetna**, as soon as Thomas registers: client-credentials pair in `.env` only (`DIRECTORY_AETNA_CLIENT_ID/_SECRET`), token in process memory, status `needs_key` → `live` (v0.5 B5.5). Same pattern later for HealthSpring, Wellpoint, Alignment and AZ Blue. Until then: "can't check automatically" + links to the carrier's directory page and Plan Finder. | **Needs Thomas:** (1) decide to register; (2) create the Aetna developer-portal account and app in his name and accept Aetna's terms (counsel via Q9 if unsure); (3) put the two values in the server and coding-host `.env` himself (never in chat or git). Optional: approve a request to Aetna for unauthenticated access citing CMS's 2026-06-24 memo (separate, approval-gated message). | Verified 2026-11-21: Aetna's `/metadata` is public, but `Practitioner` and `InsurancePlan` return 401 "Invalid client id or secret". CMS's 2026-06-24 HPMS memo says CMS must reach the endpoint without client registration, but that binds CMS's access, not ours. Registration is an account and terms decision only Thomas can make. |
| Q15 | Which carriers' directories first | **All 16 Maricopa carriers get an entry** (Thomas: "all carriers in Maricopa must in"); order: the 5 live public APIs (Humana, UHC done; add Devoted, Wellcare/Centene, Molina), then keyed ones as Thomas registers (Aetna first), then re-check the 6 "not found/broken" monthly. A coverage check fails if any Maricopa MA contract has no entry. | Resolved (proposed by Philip, pending Thomas sign-off) | Carrier list from the CMS CY2027 Landscape (16 parent orgs, 101 plan segments); endpoint checks 2026-11-21 (v0.5 B5.2 with sources). |
| Q16 | Dental in the yearly total | **No.** The dental-use preset (v0.5 B4) is a separate, labelled estimate line; never in the yearly total, deltas or ranking. | Resolved (proposed by Philip, pending Thomas sign-off) | No CMS price data for dental work; mixing assumed prices into CMS-based totals would make rankings depend on unverified numbers. |
| Q17 | Carrier SB/EOC fetching | **Links only (WP14, v0.5 B3), after Thomas enrolls (Nov 24).** CMS PBP Section A web addresses for every plan, verified carrier PDFs where a carrier's robots.txt and terms allow, Plan Finder links; never numbers from documents; skip any carrier whose terms forbid automated access. | Resolved (proposed by Philip, pending Thomas sign-off) | Verified 2026-11-21: PBP Section A has carrier website, formulary and pharmacy URLs for all 101 Maricopa plan segments and provider-directory URLs for all 92 MA segments. |
| Q18 | Baseline PDP choice | **Lowest estimated cost for the user's drugs** (premium + drug midpoint), lowest premium when no drugs; tie → lower worst case → plan_key | Resolved (proposed by Philip, pending Thomas sign-off). Implemented in WP11 (B2 test). | Same formula for every PDP keeps neutrality; the user can still pick any PDP in the Original Medicare rows. |
| Q19 | Part A premium in the baseline | **$0** with the note "Part A premium assumed $0 (most people with 40+ quarters …)"; $328 / $597 otherwise | Resolved (proposed by Philip, pending Thomas sign-off). Implemented (`cost/baseline.py` `PART_A_NOTE`). | 2027 amounts **V** (Federal Register 2026-23603). An intake toggle for fewer quarters can come later. |
| Q20 | Medigap default in the baseline | **None** (worst case "no limit"); the user may pick G / N / HDG and enter a quote | Resolved (proposed by Philip, pending Thomas sign-off). Implemented in WP11. | No CMS Medigap premium data; showing a Medigap plan without a real quote would invent a number. |
| Q21 | Baseline in the ranked list | **Pinned, unranked** (`rank=null`), `delta_vs_baseline_cents` on every row | Resolved (proposed by Philip, pending Thomas sign-off). Implemented in WP11 (B7 test). | Keeps the v0.3 ranking unchanged and makes the "standard" comparison explicit. |

## v0.5 open decisions (2026-11-21, `DESIGN-v0.5-ADDENDUM.md`)

| # | Decision | Proposal | Status |
|---|---|---|---|
| Q22 | Source for the dental-use preset's assumed prices (v0.5 B4.3) | WP17 finds a public, citable per-service source for the Phoenix area (candidate: FAIR Health Consumer); until Thomas approves it, the preset runs in coverage-only mode (no dollar estimates) | **Needs Thomas** to approve the source once WP17 proposes it |

## Status of earlier items (2026-11-21)

- **Q9 legal review before the Nov 25 launch:** now a work package with a counsel packet and a Mon Nov 24, 5 PM MST
  deadline (v0.5 addendum B10, WP23). **Needs Thomas** to choose and engage counsel and make the go/no-go call.
- **Q10 default session mode:** no longer a default Thomas may change. No-save is a hard requirement (v0.5 B2, WP16).
