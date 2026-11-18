"""Build the configured provider (and optional fallback) from settings. No provider → no-LLM mode."""

from __future__ import annotations

import contextlib

import httpx

from selector.agent.providers.anthropic import AnthropicProvider
from selector.agent.providers.base import ChatProvider, ProviderConfigError
from selector.agent.providers.fake import FakeProvider
from selector.agent.providers.openai_compat import XAI_BASE, OpenAICompatProvider
from selector.config import Settings

SUPPORTED = ("anthropic", "xai", "openai_compat", "fake")
LABELS = {"anthropic": "Anthropic", "xai": "xAI", "openai_compat": "OpenAI-compatible provider", "fake": "Demo"}


def _make(name: str, model: str, s: Settings, client: httpx.Client | None) -> ChatProvider:
    common = {
        "timeout_s": s.llm_timeout_s,
        "max_output_tokens": s.llm_max_output_tokens,
        "temperature": s.llm_temperature,
        "client": client,
    }
    if name == "anthropic":
        return AnthropicProvider(s.anthropic_api_key.get_secret_value(), model, base_url=s.llm_base_url, **common)  # type: ignore[arg-type]
    if name == "xai":
        key = s.xai_api_key.get_secret_value() or s.openai_compat_api_key.get_secret_value()
        return OpenAICompatProvider(
            key,
            model,
            base_url=s.llm_base_url or XAI_BASE,
            name="xai",
            max_tokens_param="max_completion_tokens",
            **common,  # type: ignore[arg-type]
        )
    if name == "openai_compat":
        return OpenAICompatProvider(
            s.openai_compat_api_key.get_secret_value(),
            model,
            base_url=s.llm_base_url,
            **common,  # type: ignore[arg-type]
        )
    if name == "fake":
        return FakeProvider(model)
    raise ProviderConfigError(f"LLM_PROVIDER={name!r} is not supported in the MVP (use one of {SUPPORTED})")


def build_provider(s: Settings, client: httpx.Client | None = None) -> ChatProvider | None:
    """The primary provider, or None when `LLM_PROVIDER` is blank (the app then runs in no-LLM mode)."""
    if not s.llm_provider:
        return None
    return _make(s.llm_provider, s.llm_model, s, client)


def build_provider_chain(s: Settings, client: httpx.Client | None = None) -> list[ChatProvider]:
    """[primary, fallback?]. A misconfigured fallback is skipped (the primary still works)."""
    primary = build_provider(s, client)
    if primary is None:
        return []
    chain = [primary]
    if s.llm_fallback_provider:
        with contextlib.suppress(ProviderConfigError):
            chain.append(_make(s.llm_fallback_provider, s.llm_fallback_model or s.llm_model, s, client))
    return chain


def provider_label(s: Settings) -> str | None:
    """Named on the consent screen (OPEN-QUESTIONS Q8). Never includes keys."""
    if not s.llm_provider:
        return None
    label = LABELS.get(s.llm_provider, s.llm_provider)
    return f"{label} ({s.llm_model})" if s.llm_model else label
