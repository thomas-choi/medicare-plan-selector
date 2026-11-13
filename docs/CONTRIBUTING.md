# Contributing

Thanks for helping. This tool is independent and free, and it stays that way: no commissions, sponsor fields,
ranking boosts, analytics or trackers will be accepted.

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
