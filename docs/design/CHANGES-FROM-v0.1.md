# Changes from v0.1 → v0.2

These changes follow Thomas's answers on 2026-11-12.

| Area | v0.1 | v0.2 |
|---|---|---|
| Name and repo | `medicare-plan-advisor`, private | **`medicare-plan-selector`**, public at https://github.com/thomas-choi/medicare-plan-selector |
| Audience | Thomas only, local | **Public multi-user web service**, anonymous sessions, optional accounts later |
| Hosting | 127.0.0.1 | **`med.thomas-choi.com:<MED_PUBLIC_PORT>`**, docker compose, nginx TLS, rate limits |
| DB | SQLite file per year | **MySQL 8**, SQLAlchemy + **Alembic**; plan data keyed by a `plan_year` column (optional LIST partitions); staging → swap per year |
| Backend | FastAPI recommended | **FastAPI confirmed** |
| LLM | One provider, pinned | **Provider abstraction in `.env`:** `LLM_PROVIDER` (anthropic, openai, openai_compat/xAI, ollama), `LLM_MODEL`, `LLM_BASE_URL`, key variables, fallback, pricing for the budget ledger |
| Feedback | none | **New subsystem (§7):** per-recommendation thumbs and rating plus text, session outcome (chosen or enrolled), general feedback, bug reports; consent, PHI redactor, PHI opt-in; admin list and CSV export with audit; feedback becomes regression tests and prompt versions |
| Privacy | Local file, git-ignored | Consent screen; server-side profile with **AES-GCM field encryption**; retention purge; **delete-my-data**; body-free logs; no third-party analytics |
| Abuse and cost | n/a | nginx `limit_req`, per-session and per-IP quotas, **global daily LLM budget cap**, captcha option, input limits, **no-LLM mode** when the cap is hit |
| Security | Basic | Prompt-injection defenses (read-only tools, server-injected `session_id`, validator, policy check, sanitized rendering, red-team tests) |
| Compliance | Disclaimer only | Disclaimers (not an agent or broker, not affiliated with CMS, estimates only, confirm via Plan Finder, 1-800-MEDICARE or SHIP); researched notes on **HIPAA** (45 CFR 160.103), **FTC HBNR** (16 CFR 318, 2024 amendments) and **CMS marketing/TPMO** (42 CFR 422.2260), all marked as our unverified reading; **neutrality** rules (no commissions or sponsor bias; ranking from user weights only) |
| Public repo hygiene | n/a | LICENSE (choose), `SECURITY.md`, `CONTRIBUTING.md`, `DATA-SOURCES.md`, `.env.example`, pre-commit + gitleaks, GitHub push protection |
| ZIP→county | HUD file or API | **HUD API token** used (`HUD_API_TOKEN`); new **`HUD-API-SETUP.md`** |
| Timeline | MVP Nov 22, enroll Dec 3 | **MVP Tue Nov 17**, **cloud test Wed Nov 18**, **Thomas enrolls by Tue Nov 24**, **public launch Wed Nov 25**, support window through Dec 7 |
| Scope | Medigap in v1 | **MVP cut:** MA/MA-PD plus PDP; minimal PBP; Medigap, captcha, SSO admin, accounts and the cost chart polish moved after the MVP |
| Fallback | No-LLM report CLI | No-LLM **web mode** (form → table), which doubles as the budget-cap fallback |
| Open questions | 14 | 9 remaining (license, admin auth, budget cap, retention, port/TLS, analytics, captcha, provider, legal review); per-user items moved into intake |

The v0.1 folder and archive are unchanged.
