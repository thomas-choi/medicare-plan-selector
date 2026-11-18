"""Fake provider: no network, deterministic. Used by tests (scripted) and for local demos (`LLM_PROVIDER=fake`).

Demo behaviour: on a user turn it calls `explain_plan` when a plan ID is mentioned, else `compare_plans`; on a tool
result it writes a short summary using only numbers from that tool result (so the validator passes).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from selector.agent.providers.base import ChatMessage, Completion, ToolCall, ToolSpec, Usage

PLAN_KEY_RE = re.compile(r"\b([HRSE]\d{4})[-_](\d{3})(?:[-_](\d{1,3}))?\b", re.I)
Script = list[Completion | Callable[[str, list[ChatMessage], list[ToolSpec]], Completion]]


def dollars(cents: int | None) -> str:
    if cents is None:
        return "no yearly cap"
    return f"${cents / 100:,.2f}"


class FakeProvider:
    name = "fake"

    def __init__(self, model: str = "fake-demo-1", script: Script | None = None) -> None:
        self.model = model or "fake-demo-1"
        self._script = list(script) if script is not None else None
        self.calls: list[tuple[str, list[ChatMessage], list[str]]] = []
        self._n = 0

    def complete(self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> Completion:
        self.calls.append((system, list(messages), [t.name for t in tools]))
        if self._script is not None:
            if not self._script:
                return self._done("(script exhausted)")
            step = self._script.pop(0)
            return step(system, messages, tools) if callable(step) else step
        return self._demo(messages, tools)

    def _done(self, text: str, calls: list[ToolCall] | None = None) -> Completion:
        return Completion(text, calls or [], Usage(100, 40), self.name, self.model, "end_turn")

    def _call(self, name: str, args: dict[str, Any]) -> Completion:
        self._n += 1
        return self._done("", [ToolCall(f"fake_{self._n}", name, args)])

    def _demo(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> Completion:
        last = messages[-1] if messages else ChatMessage("user", "")
        names = {t.name for t in tools}
        if last.role == "tool":
            return self._done(self._summarize(last.tool_name or "", last.content))
        m = PLAN_KEY_RE.search(last.content)
        if m and "explain_plan" in names:
            key = f"{m.group(1).upper()}_{m.group(2)}_{int(m.group(3) or 0)}"
            return self._call("explain_plan", {"plan_key": key})
        if "compare_plans" in names:
            return self._call("compare_plans", {"limit": 3})
        return self._done("I can only help compare Medicare plans with the official CMS data.")

    @staticmethod
    def _summarize(tool: str, content: str) -> str:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return "Something went wrong reading the plan data. Please try again."
        if "error" in data:
            return str(data.get("user_message") or "I couldn't do that. Please check the intake form.")
        if tool == "compare_plans":
            top = data.get("top", [])
            if not top:
                return "No plans matched your choices. Try relaxing a must-have in the intake form."
            lines = [f"Here are your top {len(top)} plans by estimated yearly cost (estimates only):"]
            for p in top:
                lines.append(
                    f"{p['rank']}. {p['plan_name']} ({p['plan_key']}): about {dollars(p['total_est_cents'])} a year; "
                    f"worst case {dollars(p['worst_case_cents'])}."
                )
            lines.append(
                "Before you decide, confirm these in Medicare Plan Finder and call each plan to check your doctors."
            )
            return "\n".join(lines)
        if tool == "explain_plan":
            p = data.get("plan", {})
            return (
                f"{p.get('plan_name', 'This plan')} ({p.get('plan_key', '')}): monthly premium "
                f"{dollars(p.get('monthly_premium_cents'))}, maximum out-of-pocket {dollars(p.get('moop_cents'))}. "
                "Call the plan to confirm your doctors are in its network."
            )
        return "Done."
