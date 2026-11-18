"""OpenAI-compatible Chat Completions adapter (POST {base}/chat/completions) with function tools.

Used for `openai_compat` (any compatible endpoint, `LLM_BASE_URL` required) and `xai` (base URL
`https://api.x.ai/v1`, Bearer `XAI_API_KEY`; verified against docs.x.ai 2026-11-17: OpenAI-compatible
`/v1/chat/completions`, `tools[].function`, `tool_calls` in the reply, role `tool` results, `max_completion_tokens`).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from selector.agent.providers.base import (
    ChatMessage,
    Completion,
    ProviderConfigError,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    ToolSpec,
    Usage,
    classify_http_error,
)

XAI_BASE = "https://api.x.ai/v1"


class OpenAICompatProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str,
        name: str = "openai_compat",
        timeout_s: float = 60,
        max_output_tokens: int = 1500,
        temperature: float = 0.2,
        max_tokens_param: str = "max_tokens",
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        if not api_key:
            raise ProviderConfigError(f"{name}: API key is not set")
        if not model:
            raise ProviderConfigError(f"{name}: LLM_MODEL is not set")
        if not base_url:
            raise ProviderConfigError(f"{name}: LLM_BASE_URL is not set")
        self.model = model
        self._key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._max_tokens = max_output_tokens
        self._max_tokens_param = max_tokens_param
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_s)

    @staticmethod
    def to_wire(system: str, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        return out

    def complete(self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self.to_wire(system, messages),
            "temperature": self._temperature,
            self._max_tokens_param: self._max_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        try:
            r = self._client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as e:
            raise ProviderUnavailable(f"{self.name}: timeout") from e
        except httpx.TransportError as e:
            raise ProviderUnavailable(f"{self.name}: {type(e).__name__}") from e
        if r.status_code != 200:
            raise classify_http_error(r.status_code, self.name)
        try:
            data = r.json()
            msg = data["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            raise ProviderError(f"{self.name}: unexpected response shape") from e
        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                calls.append(ToolCall(tc.get("id", ""), fn.get("name", ""), args if isinstance(args, dict) else {}))
            except json.JSONDecodeError:
                calls.append(ToolCall(tc.get("id", ""), fn.get("name", ""), {}, raw_arguments=str(raw)[:200]))
        usage = data.get("usage") or {}
        return Completion(
            text=msg.get("content") or "",
            tool_calls=calls,
            usage=Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
            provider=self.name,
            model=str(data.get("model") or self.model),
            stop_reason=data["choices"][0].get("finish_reason"),
        )
