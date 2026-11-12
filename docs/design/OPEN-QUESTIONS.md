# Open Questions v0.3: defaults accepted, pending Thomas's objection

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
