# Claude Code Worker Handoff: Medicare Plan Selector MVP

**Authority:** the signed-off design v0.3 in `docs/design/`, signed off by Thomas on 2026-11-12 with the no-save addition. Where this brief and `docs/design/*` disagree, ask Thomas.
**Owner and approver:** Thomas Choi. **Architect and reviewer:** Philip. All dates and times are MST (America/Phoenix).

## 1. Workflow (Thomas's process)
1. **Read** `docs/design/README.md`, `DESIGN.md`, `IMPLEMENTATION-PLAN.md`, `OPEN-QUESTIONS.md` and `HUD-API-SETUP.md`, then scan the repository.
2. **Stay in Plan mode.** Ask Thomas every clarifying or blocking question about the design in one batch. Then propose a plan that follows the work packages WP0–WP8, in MVP order.
3. **Wait for Thomas's approval.** He chooses "Yes, and use auto mode". If Auto mode isn't offered, he chooses manual edit approval, **never** the bypass-permissions option.
4. **Code in Auto mode.** Write **cumulative regression tests from the first commit-worthy change.** The suite only grows, and every bug gets a failing test first. Run `make test` before you report any work package as done.
5. You **may create a local feature branch**, e.g. `feat/mvp`. Commits go on that branch, never on `main`.
6. At the end of each work package, report: files changed, test counts (passed/total), what is unverified, and what's next.

## 2. Hard rules
- **Never** push, merge, rebase onto `main`, tag, force-push, deploy, or commit to `main` without Thomas's explicit approval.
- **Commit only** after a commit signal from Philip or Thomas.
- **Never** commit secrets, `.env*` (other than `.env.example`), API keys, tokens, real user data or PHI, or raw CMS downloads. Run `pre-commit` (with gitleaks) before every proposed commit.
- **Never read** `.env` files on the host, and never print tokens. Use `.env.example` placeholders.
- **Do not change `LICENSE`**, which is GPL-3.0 from Thomas, or the existing `README.md` content without approval. Appending a short "Docs" section to `README.md` is OK only if Thomas agrees.
- **Stop and ask** when:
  - a CMS file's shape differs from the design, or a PBP field mapping is ambiguous;
  - legal, compliance or disclaimer wording comes up;
  - something would need to weaken a privacy guarantee, especially No-save mode (§8.5);
  - you'd need a new external service or paid API.
- **Package installs:** use the project's own lockfiles (`pyproject`/`uv` or `pip`, `npm`). No global installs and no `sudo`. Docker is allowed only via the repo's `docker compose` files, for tests.
- Don't scrape Medicare.gov. Don't add analytics, trackers, sponsor fields or ranking boosts.

## 3. MVP scope and dates
- **MVP scope:** see the "MVP scope" table in IMPLEMENTATION-PLAN. In short:
  - MA/MA-PD + PDP;
  - Landscape, Part D formulary/cost/insulin and minimal PBP ingest into MySQL by `plan_year`;
  - HUD ZIP→county;
  - the cost engine;
  - agent + tools + validator, with `anthropic`, `openai_compat` and `fake` providers;
  - chat + canvas (table, side-by-side, checklist);
  - **No-save (default) and Saved session modes**;
  - feedback with counters, a team message, admin export;
  - quotas and budget cap;
  - no-LLM mode;
  - disclaimers;
  - repo hygiene.
- **Dates:**

| Date | Milestone |
|---|---|
| Fri Nov 13 | M0+M1 (scaffold + ingest) |
| Sat Nov 14 | M2 (cost engine) |
| Sun Nov 15 | M3 (agent + `EphemeralSessionStore` first) |
| Mon Nov 16 | M4 (frontend, consent, feedback) |
| **Tue Nov 17** | **MVP** |
| Wed Nov 18 | Cloud test deploy, done by Thomas |
| Tue Nov 24 | Thomas enrolls |
| Wed Nov 25 | Public launch |

- **Fallback:** if M3 isn't green by the night of Nov 15, ship the **no-LLM mode** first.
- **Must-pass for the MVP:** the golden row `2027/H0028_028_0`, the cost cases, the red-team set, the privacy tests and **No-save N1–N9**.

## 4. Operator steps for Thomas on Ubuntu ml3090
```bash
# 1. Clone (first time) — or `git -C ... pull --ff-only` if it already exists
git clone https://github.com/thomas-choi/medicare-plan-selector.git /home/thomas/projects/medicare-plan-selector
cd /home/thomas/projects/medicare-plan-selector
git log --oneline -3          # should show the docs commit on top of 3ebd2ec

# 2. (Recommended) local guardrails for this Claude session — not committed
mkdir -p .claude
cat > .claude/settings.local.json <<'JSON'
{
  "permissions": {
    "deny": [
      "Bash(git push:*)", "Bash(git merge:*)", "Bash(git rebase:*)", "Bash(git tag:*)",
      "Bash(git reset --hard:*)", "Bash(git checkout main:*)", "Bash(git switch main:*)",
      "Bash(sudo:*)", "Read(./.env)", "Read(./.env.*)"
    ],
    "ask": ["Bash(git commit:*)", "Bash(docker:*)", "Bash(pip install:*)", "Bash(npm install:*)"]
  }
}
JSON
echo ".claude/settings.local.json" >> .git/info/exclude

# 3. Start Claude Code in Plan mode from the repo folder
claude --permission-mode plan
```
4. In Claude, run **`/status`** and send Philip just the **Model** line. If you want a specific model, use `/model`.
5. Paste the **kickoff prompt** below.
6. Answer Claude's questions. Optionally, paste its questions and plan to Philip for review. Then approve with **"Yes, and use auto mode"**. If that option isn't offered, pick manual approval, **never** the bypass option.
7. You'll see changes appear live in `/home/thomas/projects/medicare-plan-selector`. Get the HUD token per `docs/design/HUD-API-SETUP.md`, and put it only in your local or server `.env`.

The rules in step 2 match commands as they are typed. They are guardrails, not a sandbox. The rule syntax follows Claude Code's permission settings and should be checked against the current docs at https://code.claude.com/docs/en/permission-modes.

## 5. Kickoff prompt (paste exactly)
```
Read docs/CLAUDE-HANDOFF.md first; it is your task brief. Then read docs/design/README.md, DESIGN.md, IMPLEMENTATION-PLAN.md, OPEN-QUESTIONS.md and HUD-API-SETUP.md, and scan this repository. Stay in plan mode. Ask me all clarifying or blocking questions about the design in one batch (including anything unclear about No-save mode in DESIGN §8.5, the MySQL/Redis setup, the LLM provider in .env, and the MVP cut). Then propose a work-package plan (WP0–WP8) that reaches the MVP by Tue Nov 17 with cumulative regression tests from the start, including No-save tests N1–N9. Do not edit files, install packages, commit or push until I approve the plan. You may later create a local feature branch (e.g. feat/mvp); never push, merge, tag, deploy or commit to main; commit only when I or Philip say so; never read .env files or commit secrets/PHI/raw CMS files; do not change LICENSE or README.md.
```
