"""LLM provider adapters behind one `ChatProvider` interface (DESIGN §6.4), selected by `LLM_PROVIDER`."""

from __future__ import annotations

from selector.agent.providers.base import (
    ChatMessage,
    ChatProvider,
    Completion,
    ProviderConfigError,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    ToolSpec,
    Usage,
)
from selector.agent.providers.factory import build_provider, build_provider_chain, provider_label

__all__ = [
    "ChatMessage",
    "ChatProvider",
    "Completion",
    "ProviderConfigError",
    "ProviderError",
    "ProviderUnavailable",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "build_provider",
    "build_provider_chain",
    "provider_label",
]
