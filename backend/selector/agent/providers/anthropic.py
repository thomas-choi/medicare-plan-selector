"""Anthropic Messages API adapter with tool use (POST {base}/v1/messages, `anthropic-version: 2023-06-01`)."""

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

DEFAULT_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "",
        timeout_s: float = 60,
        max_output_tokens: int = 1500,
        temperature: float = 0.2,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ProviderConfigError("anthropic: ANTHROPIC_API_KEY is not set")
        if not model:
            raise ProviderConfigError("anthropic: LLM_MODEL is not set")
        self.model = model
        self._key = api_key
        self._url = (base_url or DEFAULT_BASE).rstrip("/") + "/v1/messages"
        self._max_tokens = max_output_tokens
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_s)

    @staticmethod
    def to_wire(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                out.append({"role": "assistant", "content": blocks or m.content})
            else:  # tool result → a user turn with a tool_result block (merged with an adjacent one)
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def complete(self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "system": system,
            "messages": self.to_wire(messages),
        }
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        try:
            r = self._client.post(
                self._url,
                json=body,
                headers={"x-api-key": self._key, "anthropic-version": API_VERSION, "content-type": "application/json"},
            )
        except httpx.TimeoutException as e:
            raise ProviderUnavailable("anthropic: timeout") from e
        except httpx.TransportError as e:
            raise ProviderUnavailable(f"anthropic: {type(e).__name__}") from e
        if r.status_code != 200:
            raise classify_http_error(r.status_code, self.name)
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise ProviderError("anthropic: response is not JSON") from e
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                inp = block.get("input")
                calls.append(ToolCall(block["id"], block["name"], inp if isinstance(inp, dict) else {}))
        usage = data.get("usage") or {}
        return Completion(
            text="".join(texts),
            tool_calls=calls,
            usage=Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))),
            provider=self.name,
            model=str(data.get("model") or self.model),
            stop_reason=data.get("stop_reason"),
        )
