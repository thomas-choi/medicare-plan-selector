# Changes from v0.2 → v0.3

Thomas signed off on v0.2 on 2026-11-12, with one addition: *"add an option to the platform that not saving any data (in database) at all after the session is finished."*

| Area | Change |
|---|---|
| Status | All docs are marked **Signed off by Thomas 2026-11-12 with the no-save addition**. |
| **No-save mode** (DESIGN §8.5) | New consent choice, **preselected by default** (`DEFAULT_SESSION_MODE=nosave`). Profile, chat, LLM transcripts and recommendations live only in **Redis with no persistence on tmpfs**, encrypted with a per-session key held only in the cookie. They are wiped on "End session & erase", after 30 min idle, at the 4 h absolute cap, on API restart (startup flush) and on Redis restart. A **MySQL write guard** raises an error on any user-table write. Nothing about the session appears in logs. Users can download their comparison client-side. |
| Feedback in No-save | Inline 👍/👎 and outcome only increment anonymous `feedback_counter` rows (no session link, no text). An explicit **"Send a message to the team"** form states that the message will be stored (redacted, 365 days, unlinked) before submit. It is stored with `session_id NULL, mode='nosave'`. |
| Cost ledger | New `usage_daily` aggregate (tokens and cost by day, provider, model and mode; no session or IP). `usage_ledger` is saved mode only. No-save quotas are Redis counters keyed by a daily-salted IP HMAC with a 24 h TTL. |
| LLM retention caveat | The consent screen states that the provider's own retention still applies. Use a zero-retention setting where offered (U). |
| Architecture and deploy | `redis` service added (`--save "" --appendonly no`, tmpfs, internal network, password). New `store/` package. |
| Plan | Fits the MVP (Nov 17): Redis is in the M0 compose; `EphemeralSessionStore` comes first in M3 (Nov 15); the consent mode picker and counters are in M4 (Nov 16). |
| Tests | New **N1–N9** no-save regression tests: zero-write row counts and checksums, write guard, end purge, idle and absolute TTL, API restart, Redis restart and no persistence files, log sentinels, ciphertext at rest, browser storage empty, explicit message stored unlinked. They are added to the definition of done. |
| License | The repo already contains **GPL-3.0** (initial commit). The v0.2 Apache-2.0 default is replaced by "keep GPL-3.0", and the AGPL option is noted. No LICENSE change. |
| Open questions | Defaults accepted pending Thomas's objection. Added Q10 (default mode) and Q11 (no-save timers). |
| New doc | `CLAUDE-HANDOFF.md` (worker brief + operator steps). |
| Doc location | In the repo: `docs/design/*` and `docs/CLAUDE-HANDOFF.md`. |
