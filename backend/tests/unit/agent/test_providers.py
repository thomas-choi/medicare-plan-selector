"""Provider contract tests against recorded response shapes (no network, no keys)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from selector.agent.providers import (
    ChatMessage,
    ProviderConfigError,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    ToolSpec,
    build_provider,
    build_provider_chain,
    provider_label,
)
from selector.agent.providers.anthropic import AnthropicProvider
from selector.agent.providers.openai_compat import OpenAICompatProvider
from selector.config import Settings

KEY = "test-key-not-real"
TOOLS = [ToolSpec("compare_plans", "rank", {"type": "object", "properties": {"limit": {"type": "integer"}}})]
HISTORY = [
    ChatMessage("user", "<user_message>hi</user_message>"),
    ChatMessage("assistant", "", tool_calls=[ToolCall("t1", "compare_plans", {"limit": 3})]),
    ChatMessage("tool", '{"top": []}', tool_call_id="t1", tool_name="compare_plans"),
]
ANTHROPIC_REPLY = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-test",
    "content": [
        {"type": "text", "text": "Let me compare."},
        {"type": "tool_use", "id": "toolu_1", "name": "compare_plans", "input": {"limit": 3}},
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 120, "output_tokens": 30},
}
OPENAI_REPLY = {
    "id": "c1",
    "model": "grok-test",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "compare_plans", "arguments": '{"limit":2}'},
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 200, "completion_tokens": 20},
}


@respx.mock
def test_anthropic_request_and_parse() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_REPLY)
    )
    p = AnthropicProvider(KEY, "claude-test", client=httpx.Client())
    c = p.complete("SYSTEM", HISTORY, TOOLS)
    req = route.calls.last.request
    assert req.headers["x-api-key"] == KEY and req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["system"] == "SYSTEM" and body["tools"][0]["input_schema"]["type"] == "object"
    assert body["messages"][1]["content"][0] == {
        "type": "tool_use",
        "id": "t1",
        "name": "compare_plans",
        "input": {"limit": 3},
    }
    assert body["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": '{"top": []}'}],
    }
    assert c.text == "Let me compare." and c.tool_calls[0].name == "compare_plans"
    assert (c.usage.tokens_in, c.usage.tokens_out, c.provider) == (120, 30, "anthropic")


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (429, ProviderUnavailable),
        (529, ProviderUnavailable),
        (500, ProviderUnavailable),
        (400, ProviderError),
        (401, ProviderError),
    ],
)
@respx.mock
def test_anthropic_errors(status: int, exc: type[Exception]) -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(status, json={}))
    with pytest.raises(exc) as ei:
        AnthropicProvider(KEY, "m", client=httpx.Client()).complete("s", HISTORY, [])
    assert KEY not in str(ei.value)
    if status < 429:
        assert not isinstance(ei.value, ProviderUnavailable)


@respx.mock
def test_timeout_is_unavailable() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderUnavailable):
        AnthropicProvider(KEY, "m", client=httpx.Client()).complete("s", HISTORY, [])


@respx.mock
def test_xai_request_and_parse() -> None:
    route = respx.post("https://api.x.ai/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_REPLY))
    s = Settings(llm_provider="xai", llm_model="grok-test", xai_api_key=KEY)
    p = build_provider(s, client=httpx.Client())
    assert p is not None and p.name == "xai"
    c = p.complete("SYSTEM", HISTORY, TOOLS)
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"limit": 3}'
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": '{"top": []}'}
    assert body["max_completion_tokens"] == 1500 and body["tools"][0]["type"] == "function"
    assert c.tool_calls[0].arguments == {"limit": 2} and c.usage.tokens_in == 200 and c.provider == "xai"


@respx.mock
def test_openai_compat_bad_json_arguments_and_503() -> None:
    bad = json.loads(json.dumps(OPENAI_REPLY))
    bad["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    respx.post("https://llm.example/v1/chat/completions").mock(
        side_effect=[httpx.Response(200, json=bad), httpx.Response(503)]
    )
    p = OpenAICompatProvider(KEY, "m", base_url="https://llm.example/v1", client=httpx.Client())
    c = p.complete("s", HISTORY, TOOLS)
    assert c.tool_calls[0].raw_arguments == "{not json" and c.tool_calls[0].arguments == {}
    with pytest.raises(ProviderUnavailable):
        p.complete("s", HISTORY, TOOLS)


def test_factory_config() -> None:
    assert build_provider(Settings(llm_provider="")) is None
    with pytest.raises(ProviderConfigError):
        build_provider(Settings(llm_provider="anthropic", llm_model="m"))  # no key
    with pytest.raises(ProviderConfigError):
        build_provider(Settings(llm_provider="openai_compat", llm_model="m", openai_compat_api_key=KEY))  # no base
    with pytest.raises(ProviderConfigError):
        build_provider(Settings(llm_provider="ollama", llm_model="m"))  # post-MVP
    assert build_provider(Settings(llm_provider="fake")).name == "fake"  # type: ignore[union-attr]
    chain = build_provider_chain(
        Settings(
            llm_provider="anthropic", llm_model="m", anthropic_api_key=KEY, llm_fallback_provider="xai", xai_api_key=KEY
        )
    )
    assert [p.name for p in chain] == ["anthropic", "xai"]
    assert provider_label(Settings(llm_provider="xai", llm_model="grok-x")) == "xAI (grok-x)"
    assert provider_label(Settings(llm_provider="")) is None


def test_default_provider_per_design_is_documented() -> None:
    """DESIGN §6.4 shows LLM_PROVIDER=anthropic; .env.example defaults to fake for keyless local runs."""
    from selector.config import REPO_ROOT

    text = (REPO_ROOT / ".env.example").read_text()
    assert "anthropic (default per DESIGN §6.4)" in text and "LLM_PROVIDER=fake" in text
