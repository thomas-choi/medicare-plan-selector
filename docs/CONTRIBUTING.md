# Contributing

Thanks for helping. This tool is independent and free, and it stays that way: no commissions, sponsor fields,
ranking boosts, analytics or trackers will be accepted.

## Repository rules (Thomas, 2026-11-21)
These apply to every change, by people and by agents (the Claude coding worker included). Design reference:
[DESIGN-v0.5-ADDENDUM.md B0.1](design/DESIGN-v0.5-ADDENDUM.md).

- **R-A. README.md does not track detailed configuration** (unless a change corrects wrong content). README keeps the
  overview, a quick start and links. Configuration detail (env variables, make targets, layouts, operator steps) goes
  in a design document (`docs/design/`), a report (`qa/`) or [OPERATION.md](OPERATION.md).
- **R-B. After each task is done, add a [CHANGELOG.md](CHANGELOG.md) entry** with:
  - **When:** date and time, America/Phoenix (MST), e.g. `2026-11-21 01:30 MST`;
  - **Who:** your name (agent or person);
  - **Reference:** the document and section (or the chat message) the task came from;
  - **What:** one bullet per item of the task, documentation changes included (name each file).

## Ground rules
- **Tests are required.** The regression suite only grows. Every bug fix starts with a failing test.
- **No real user data** in issues, pull requests, fixtures or logs. Use obviously fake sentinels
  (ZIP `99999`, drug `zzfakedrug`, doctor `Dr Sentinel`).
- **No raw CMS downloads** in git. Fixtures are small public samples (≤ 200 rows) with vintage and sha256,
  attributed in [DATA-SOURCES.md](DATA-SOURCES.md).
- **No secrets.** Only `.env.example` (placeholders) is committed.
- Don't scrape Medicare.gov.

## Development
```bash
cd backend && uv sync          # Python 3.13
cd frontend && npm ci          # Node 20
make stack-up                  # MySQL 8.4 on 127.0.0.1:3307, Redis 7.4 on 127.0.0.1:6380
make test                      # lint + full backend/frontend suites
make precommit                 # gitleaks, forbidden-file check, linters
```
All make targets, `.env` keys and data-store layouts: [OPERATION.md](OPERATION.md).
