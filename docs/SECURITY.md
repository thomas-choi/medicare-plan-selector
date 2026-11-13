# Security policy

Medicare Plan Selector is a public, anonymous comparison tool. It handles sensitive inputs (ZIP, drugs, doctors), so we
treat every report seriously.

## Reporting a vulnerability
- Report privately through **GitHub Security Advisories** ("Report a vulnerability" on the repository's Security tab).
- Please don't open public issues for security problems, and never include real personal or health data in a report.
- We aim to acknowledge reports within 3 days.

## Supported versions
Only the latest deployment of `main` is supported.

## What we protect (summary of DESIGN §8)
- No-save sessions (the default) keep data only in non-persistent Redis, encrypted with a key held in the user's cookie.
- Saved sessions encrypt ZIP, drug, doctor and chat text with AES-256-GCM at the application layer.
- Request bodies are never logged. There are no third-party analytics.

## Breach response runbook
The design assumes the FTC Health Breach Notification Rule (16 CFR 318) **may** apply (DESIGN §8.4, unverified).
1. **Contain:** take the service offline or disable the affected component; rotate `PROFILE_ENC_KEY`, database
   and Redis passwords, and LLM/HUD keys.
2. **Assess:** determine what data, which sessions and which time window were affected. No-save data that has expired is
   unrecoverable by design.
3. **Notify** (if the rule applies; confirm with counsel): affected individuals and the FTC without unreasonable delay,
   within the rule's deadlines; the media if 500 or more residents of one state are affected.
4. **Record** the incident, the decisions and the notifications; add regression tests for the root cause.
