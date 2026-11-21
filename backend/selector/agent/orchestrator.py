"""One chat turn: system prompt + history + wrapped user text → tool loop → validated answer (DESIGN §6).

- Tool calls run server-side with the session's `ToolContext` (the model never supplies a session id).
- The final text is sanitized and checked by the validator. On failure the model gets one correction round; if it
  fails again the user gets a deterministic summary built from the tool results.
- The fallback provider is used only when the primary is unavailable (timeout, 429, 5xx), never on validator
  failure.
- `budget_check()` runs before every model call; `usage_sink()` records tokens after it (WP5 quotas).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from selector.agent import tools as T
from selector.agent.policy import ESTIMATE_DISCLAIMER, needs_estimate_disclaimer, sanitize, wrap_user_text
from selector.agent.prompts import PROMPT_VERSION, system_prompt
from selector.agent.providers.base import ChatMessage, ChatProvider, Completion, ProviderUnavailable, Usage
from selector.agent.providers.fake import dollars
from selector.agent.validator import Facts, validate

log = logging.getLogger(__name__)
MAX_ROUNDS = 6
MAX_CALLS_PER_ROUND = 4
HISTORY_TURNS = 12


class BudgetExceeded(RuntimeError):
    """The global daily LLM budget or a per-session quota is used up: switch to no-LLM mode."""


@dataclass
class TurnResult:
    text: str
    canvas: dict[str, Any]
    citations: list[dict[str, Any]]
    tool_calls: list[dict[str, str]]  # ids and names only (bug reports never include content)
    model_id: str
    provider: str
    prompt_version: str
    validation: str  # ok | retried | fallback | no_llm
    usage: list[tuple[str, str, Usage]] = field(default_factory=list)
    profile_changed: bool = False


def deterministic_summary(canvas: dict[str, Any]) -> str:
    rows = [r for r in canvas.get("rows", []) if r.get("rank")]
    if not rows:
        return "I can show you the plan comparison table. Use the intake form to enter your ZIP code and drugs."
    lines = ["Here is the comparison from the plan data (estimates only):"]
    for r in rows[:3]:
        lines.append(f"{r['rank']}. {r['plan_name']} ({r['plan_key']}): about {dollars(r['total_est_cents'])} a year.")
    if b := canvas.get("baseline"):
        total = dollars(b["total_est_cents"])
        lines.append(f"For reference, the standard Original Medicare + Part D option: about {total} a year.")
    lines.append("Use the checklist tab to confirm your finalists with Medicare Plan Finder and each plan.")
    return "\n".join(lines)


def _dedupe(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for r in refs:
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


class Orchestrator:
    def __init__(
        self,
        providers: list[ChatProvider],
        *,
        budget_check: Callable[[], None] | None = None,
        usage_sink: Callable[[str, str, Usage], None] | None = None,
        max_rounds: int = MAX_ROUNDS,
    ) -> None:
        if not providers:
            raise ValueError("no provider configured")
        self.providers = providers
        self.budget_check = budget_check or (lambda: None)
        self.usage_sink = usage_sink or (lambda p, m, u: None)
        self.max_rounds = max_rounds

    def _complete(self, system: str, msgs: list[ChatMessage], usage: list[tuple[str, str, Usage]]) -> Completion:
        last: Exception | None = None
        for p in self.providers:
            self.budget_check()
            try:
                c = p.complete(system, msgs, T.tool_specs())
            except ProviderUnavailable as e:
                log.warning("provider unavailable: %s", type(e).__name__)
                last = e
                continue
            usage.append((c.provider, c.model, c.usage))
            self.usage_sink(c.provider, c.model, c.usage)
            return c
        raise last or ProviderUnavailable("no provider")

    def run_turn(self, ctx: T.ToolContext, history: list[ChatMessage], user_text: str) -> TurnResult:
        system = system_prompt().format(
            plan_year=ctx.plan_year, profile=json.dumps(ctx.profile.summary_for_prompt(), ensure_ascii=False)
        )
        msgs = [m for m in history[-HISTORY_TURNS * 2 :] if m.role in ("user", "assistant") and not m.tool_calls]
        msgs.append(ChatMessage("user", wrap_user_text(user_text, ctx.settings.max_message_chars)))
        facts = Facts()
        facts.add(ctx.canvas.get("rows", []))
        citations: list[dict[str, Any]] = []
        calls: list[dict[str, str]] = []
        usage: list[tuple[str, str, Usage]] = []
        retried = False
        model, provider = "", ""
        profile_before = ctx.profile
        for _ in range(self.max_rounds):
            c = self._complete(system, msgs, usage)
            model, provider = c.model, c.provider
            if c.tool_calls:
                msgs.append(ChatMessage("assistant", c.text, tool_calls=c.tool_calls[:MAX_CALLS_PER_ROUND]))
                for call in c.tool_calls[:MAX_CALLS_PER_ROUND]:
                    result = T.execute(ctx, call)
                    facts.add(result)
                    citations.extend(result.get("src_ref", []))
                    calls.append({"id": call.id, "name": call.name})
                    msgs.append(ChatMessage("tool", T.to_json(result), tool_call_id=call.id, tool_name=call.name))
                continue
            text = sanitize(c.text.strip())
            v = validate(text, facts)
            if v.ok:
                if needs_estimate_disclaimer(text):
                    text = f"{text}\n\n{ESTIMATE_DISCLAIMER}"
                return self._result(text, ctx, citations, calls, model, provider, "retried" if retried else "ok",
                                    usage, profile_before)  # fmt: skip
            log.info("validator rejected answer: %d problems", len(v.problems))
            if retried:
                break
            retried = True
            msgs.append(ChatMessage("assistant", c.text))
            msgs.append(
                ChatMessage(
                    "user",
                    "[validator] Your answer was rejected: "
                    + "; ".join(v.problems[:8])
                    + ". Rewrite it using only numbers and plan IDs from tool results, with no network claims, "
                    "enrollment promises or medical advice.",
                )
            )
        return self._result(deterministic_summary(ctx.canvas), ctx, citations, calls, model, provider, "fallback",
                            usage, profile_before)  # fmt: skip

    @staticmethod
    def _result(
        text: str,
        ctx: T.ToolContext,
        citations: list[dict[str, Any]],
        calls: list[dict[str, str]],
        model: str,
        provider: str,
        status: str,
        usage: list[tuple[str, str, Usage]],
        profile_before: Any,
    ) -> TurnResult:
        canvas = {k: v for k, v in ctx.canvas.items() if k != "profile_changed"}
        return TurnResult(text, canvas, _dedupe(citations), calls, model, provider, PROMPT_VERSION, status, usage,
                          ctx.profile is not profile_before)  # fmt: skip
