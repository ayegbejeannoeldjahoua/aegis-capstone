"""Anthropic provider client (v1.15.0): the Messages API differs from the OpenAI shape — it uses
x-api-key + anthropic-version headers, a required max_tokens, the system prompt as a top-level
field (not a message), and returns content[].text rather than choices[].message.content."""
import asyncio

import httpx
import pytest
import respx

from aegis_fabric.models import ChatMessage, ModelClient, ModelProfile


def _profile():
    return ModelProfile(
        provider="anthropic", model_id="anthropic/claude-sonnet-4-6", type="anthropic",
        base_url="https://api.anthropic.com", api_key="sk-ant-test", region="AC1",
    )


@respx.mock
def test_anthropic_request_shape_and_parse(monkeypatch):
    # the sandbox sets a SOCKS proxy env var that breaks httpx client construction; clear it so
    # respx can intercept (production is unaffected — it uses whatever proxy env is actually set).
    for v in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(v, raising=False)
    captured = {}

    def _respond(request):
        import json
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "hello from claude"}],
            "usage": {"input_tokens": 11, "output_tokens": 3},
        })

    respx.post("https://api.anthropic.com/v1/messages").mock(side_effect=_respond)

    msgs = [ChatMessage(role="system", content="be terse"),
            ChatMessage(role="user", content="hi")]
    res = asyncio.run(ModelClient()._anthropic(_profile(), msgs, 0.2))

    # response parsing
    assert res.content == "hello from claude"
    assert res.provider == "anthropic" and res.model == "anthropic/claude-sonnet-4-6"
    assert res.usage == {"prompt_tokens": 11, "completion_tokens": 3}
    # request shape: provider prefix stripped, system hoisted out of messages, required headers
    assert captured["body"]["model"] == "claude-sonnet-4-6"
    assert captured["body"]["system"] == "be terse"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert "max_tokens" in captured["body"]
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"


def test_anthropic_requires_key():
    p = _profile()
    p.api_key = None
    with pytest.raises(RuntimeError):
        asyncio.run(ModelClient()._anthropic(p, [ChatMessage(role="user", content="x")], 0.2))


def test_openai_compatible_requires_provider_specific_key():
    p = ModelProfile(
        provider="nvidia",
        model_id="nvidia/nemotron",
        type="openai_compatible",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=None,
        region="AC1",
        local=False,
    )
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY not configured"):
        asyncio.run(ModelClient()._openai_compatible(p, [ChatMessage(role="user", content="x")], 0.2))
