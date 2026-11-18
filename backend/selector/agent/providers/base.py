"""Provider-neutral message, tool and completion types.

`ChatProvider.complete(system, messages, tools) -> Completion(text, tool_calls, usage)` (DESIGN §6.4). Adapters
translate these to each vendor's wire format. `ProviderUnavailable` (timeout, 429, 5xx) is the only error that
triggers the fallback provider; it is never raised for validator failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (object)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str | None = None  # set when the model sent invalid JSON


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    provider: str
    model: str
    stop_reason: str | None = None


class ProviderError(RuntimeError):
    """Non-retryable provider error (bad request, auth). Messages never include keys or prompt text."""


class ProviderUnavailable(ProviderError):
    """Timeout, rate limit or 5xx: the fallback provider may be tried."""


class ProviderConfigError(ProviderError):
    """Provider not configured (missing key or model)."""


class ChatProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> Completion: ...


def classify_http_error(status: int, provider: str) -> ProviderError:
    if status == 429 or status >= 500:
        return ProviderUnavailable(f"{provider}: HTTP {status}")
    return ProviderError(f"{provider}: HTTP {status}")
