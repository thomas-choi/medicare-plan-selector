# medicare-plan-selector
This is an AI assistant that helps you choose the Medicare plan that best fits you.

## Overview
Medicare Plan Selector is a free, independent comparison tool. You describe your needs (ZIP code, Medicare
Advantage or Original Medicare + Part D, drugs, doctors, budget), and the assistant works from the official public
CMS plan data for your county to narrow the list to a cited top 3, with estimated yearly costs and a checklist. It
has no accounts, no commissions and no sponsored rankings. The backend is Python (FastAPI, SQLAlchemy, Alembic) on
MySQL 8.4 and Redis 7.4; the frontend is React + TypeScript + Vite.

> **Status:** MVP (WP0–WP8) plus the v0.4 work (drug search, 2027 amounts, Original Medicare + Part D baseline,
> dental, doctor directory checks, app-local Redis: WP9–WP13, WP15) on branch `fix/drug-search`, pending merge into
> `main`. Runs end to end locally with committed sample data for Maricopa County, AZ and a keyless demo assistant
> (`LLM_PROVIDER=fake`). What's next: [v0.5 design](docs/design/DESIGN-v0.5-ADDENDUM.md); history:
> [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Quick start (Ubuntu 22.04, e.g. ml3090)
Needs Docker Engine with the Compose v2 plugin, `make`, `git`, `curl`, `python3`, Node.js 20+ and
[uv](https://docs.astral.sh/uv/) (uv downloads Python 3.13 itself). Free local ports: 3307, 6380, 8000, 8080.
Nothing here needs an API key; nothing is pushed or deployed.

```bash
git clone https://github.com/thomas-choi/medicare-plan-selector.git && cd medicare-plan-selector
git checkout fix/drug-search               # until it is merged into main; then stay on main
cp .env.example .env && chmod 600 .env     # works as-is locally (LLM_PROVIDER=fake, dev passwords)
(cd backend && uv sync --frozen) && (cd frontend && npm ci)
make test                                  # lint + backend (incl. No-save N1–N9 backend parts) + Vitest
make stack-up && make ingest-dev && make app-up && make smoke
```

Open **http://127.0.0.1:8080**. Try: Start (No-save) → ZIP `85004` → Find county → RxCUI `197361` (amlodipine 5 mg) →
Add by RxCUI → Compare plans → ask the assistant "Explain H0028_028_0" → Side-by-side / Checklist → Download
comparison → End session & erase. Stop with `make app-down` (this also wipes the tmpfs databases).

Expected test result (as of WP15, 2026-11-20): **393 backend tests** and **43 Vitest tests** pass, linters clean.
Make targets, `.env` keys, the live-data MySQL layout, LAN access, real CMS ingest and optional variations (Saved
mode, a real assistant, the admin page): **[docs/OPERATION.md](docs/OPERATION.md)**. Production:
[deploy/README.md](deploy/README.md).

## Session modes
- **No-save (default):** your profile and chat live only in Redis, encrypted with a per-session key held in your
  browser cookie, and are wiped when you end the session, after 30 minutes idle, after 4 hours at most, or when the
  API restarts. Nothing is written to MySQL except anonymous counters and any message you choose to send to the team.
- **Saved:** opt in on the consent screen to keep your session for `RETENTION_DAYS`, with the ZIP, drugs, doctors
  and chat encrypted at rest. "Delete my data" removes it at any time.

Details: [DESIGN §8.5](docs/design/DESIGN.md).

## Docs
- [Design index](docs/design/README.md): [design v0.3](docs/design/DESIGN.md),
  [v0.4 addendum](docs/design/DESIGN-v0.4-ADDENDUM.md), [v0.5 addendum](docs/design/DESIGN-v0.5-ADDENDUM.md)
- [Implementation plan](docs/design/IMPLEMENTATION-PLAN.md) and [open questions](docs/design/OPEN-QUESTIONS.md)
- [Operation: running, configuring and data stores](docs/OPERATION.md) · [Deployment](deploy/README.md) ·
  [HUD API setup](docs/design/HUD-API-SETUP.md)
- [Data sources and attribution](docs/DATA-SOURCES.md)
- [Security](docs/SECURITY.md) · [Contributing and repo rules](docs/CONTRIBUTING.md) · [Changelog](docs/CHANGELOG.md)

## Disclaimer
This is an independent, free comparison tool. It is **not** a licensed insurance agent or broker, and it is **not
affiliated with or endorsed by CMS, Medicare or any plan**. Costs are estimates. Always confirm plan details on the
[Medicare.gov Plan Finder](https://www.medicare.gov/plan-compare/), at 1-800-MEDICARE, or with your
[SHIP counselor](https://www.shiphelp.org/local-medicare-help).

## License
[GPL-3.0](LICENSE)
