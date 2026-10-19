"""Cliente OpenAI-compatible contra un transporte HTTP en memoria (sin red)."""

from __future__ import annotations

import asyncio
import json
import random

import httpx
import pytest

from app.agent.llm import LLMRequest, LLMRequestError, LLMResponseError, LLMTransportError, Message, ToolSpec
from app.agent.llm.openai_compat import OpenAICompatibleClient

from .fakes import openai_body

REQ = LLMRequest(model="m", messages=(Message(role="user", content="hola"),))


def run(coro):
    return asyncio.run(coro)


def make_client(settings, handler, sleeps=None):
    async def fake_sleep(s: float) -> None:
        if sleeps is not None:
            sleeps.append(s)

    return OpenAICompatibleClient(
        settings, transport=httpx.MockTransport(handler), sleep=fake_sleep, rng=random.Random(0)
    )


def test_parses_content_usage_and_provider(make_api):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=openai_body("hola", provider="ProveedorX"))

    result = run(make_client(make_api(extra_body={"provider": {"data_collection": "deny"}}), handler).complete(REQ))
    assert result.content == "hola"
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 3
    assert result.provider == "ProveedorX"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["path"] == "/api/v1/chat/completions"
    assert seen["body"]["provider"] == {"data_collection": "deny"}
    assert seen["body"]["model"] == "m"


def test_local_without_key_sends_no_auth(make_local):
    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers
        return httpx.Response(200, json=openai_body())

    run(make_client(make_local(), handler).complete(REQ))


def test_retries_429_then_succeeds_and_honors_retry_after(make_api):
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"code": 429}})
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, json=openai_body())

    result = run(make_client(make_api(), handler, sleeps).complete(REQ))
    assert result.attempts == 3
    assert sleeps[0] == 2.0
    assert 0 <= sleeps[1] <= 1.0  # jitter con base 0.5 * 2**1


def test_retry_after_is_capped(make_api):
    sleeps: list[float] = []
    responses = iter([httpx.Response(429, headers={"retry-after": "9999"}), httpx.Response(200, json=openai_body())])
    run(make_client(make_api(), lambda r: next(responses), sleeps).complete(REQ))
    assert sleeps == [30.0]


def test_gives_up_after_max_retries(make_api):
    with pytest.raises(LLMTransportError) as exc:
        run(make_client(make_api(max_retries=2), lambda r: httpx.Response(502)).complete(REQ))
    assert exc.value.attempts == 3 and exc.value.status_code == 502


def test_timeouts_are_retried(make_api):
    state = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ReadTimeout("lento", request=req)
        return httpx.Response(200, json=openai_body())

    assert run(make_client(make_api(), handler).complete(REQ)).attempts == 2


def test_4xx_is_not_retried_and_hides_provider_text(make_api):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"code": "bad_request", "message": "eco del prompt SECRETO"}})

    with pytest.raises(LLMRequestError) as exc:
        run(make_client(make_api(), handler).complete(REQ))
    assert calls["n"] == 1
    assert "SECRETO" not in str(exc.value)
    assert "bad_request" in str(exc.value)


def test_error_inside_200(make_api):
    with pytest.raises(LLMResponseError):
        run(make_client(make_api(), lambda r: httpx.Response(200, json={"error": {"code": 502}})).complete(REQ))


def test_tool_calls_roundtrip(make_api):
    body = openai_body(None)
    body["choices"][0]["message"]["tool_calls"] = [
        {"id": "c1", "type": "function", "function": {"name": "defects_by_line", "arguments": '{"line_id": "L2"}'}}
    ]
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(json.loads(req.content))
        return httpx.Response(200, json=body)

    tool = ToolSpec(name="defects_by_line", description="d", parameters={"type": "object", "properties": {}})
    req = LLMRequest(model="m", messages=REQ.messages, tools=(tool,), json_mode=True)
    result = run(make_client(make_api(json_mode=True), handler).complete(req))
    assert result.tool_calls[0].arguments == {"line_id": "L2"}
    assert sent["tools"][0]["function"]["name"] == "defects_by_line"
    assert "response_format" not in sent  # json_mode no se mezcla con tools


def test_json_mode_only_when_destination_supports_it(make_api):
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.clear()
        sent.update(json.loads(req.content))
        return httpx.Response(200, json=openai_body())

    req = LLMRequest(model="m", messages=REQ.messages, json_mode=True)
    run(make_client(make_api(json_mode=False), handler).complete(req))
    assert "response_format" not in sent
    run(make_client(make_api(json_mode=True), handler).complete(req))
    assert sent["response_format"] == {"type": "json_object"}


def test_reasoning_tokens_and_reported_cost_are_parsed(make_api):
    """OpenRouter: tokens de razonamiento y costo real; el pin de proveedor viaja tal cual."""
    seen = {}
    pin = {"provider": {"only": ["deepinfra"], "allow_fallbacks": False}, "reasoning": {"effort": "none"}}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        body = openai_body("hola")
        body["usage"] = {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "completion_tokens_details": {"reasoning_tokens": 25},
            "cost": 0.000123,
        }
        return httpx.Response(200, json=body)

    result = run(make_client(make_api(extra_body=pin), handler).complete(REQ))
    assert result.usage.output_tokens == 40 and result.usage.reasoning_tokens == 25
    assert str(result.usage.reported_cost_usd) == "0.000123"
    assert seen["body"]["provider"] == pin["provider"]
    assert seen["body"]["reasoning"] == {"effort": "none"}


def test_missing_or_bad_cost_is_not_reported(make_api):
    def handler(req: httpx.Request) -> httpx.Response:
        body = openai_body("hola")
        body["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "cost": "n/a"}
        return httpx.Response(200, json=body)

    result = run(make_client(make_api(), handler).complete(REQ))
    assert result.usage.reported_cost_usd is None and result.usage.reasoning_tokens == 0


def test_debug_http_prints_provider_error_but_not_prompt_text(make_api, monkeypatch, capsys):
    from app.agent.llm import openai_compat

    monkeypatch.setattr(openai_compat, "_DEBUG_HTTP", True)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": 404, "message": "No endpoints found"}})

    with pytest.raises(LLMRequestError):
        run(make_client(make_api(), handler).complete(REQ))
    err = capsys.readouterr().err
    assert "HTTP 404" in err and "No endpoints found" in err
    assert '"hola"' not in err and "1 mensajes, 4 caracteres" in err


def test_default_body_uses_max_tokens_and_temperature(make_api):
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(json.loads(req.content))
        return httpx.Response(200, json=openai_body())

    run(make_client(make_api(), handler).complete(REQ))
    assert sent["max_tokens"] == REQ.max_tokens
    assert sent["temperature"] == REQ.temperature
    assert "max_completion_tokens" not in sent


def test_openai_reasoning_models_use_max_completion_tokens_and_no_temperature(make_api):
    """OpenAI (o-series, GPT-5) rechaza `max_tokens` y una `temperature` distinta de la de fábrica."""
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(json.loads(req.content))
        return httpx.Response(200, json=openai_body())

    api = make_api(
        base_url="https://api.openai.com/v1",
        provider_label="openai",
        token_param="max_completion_tokens",
        send_temperature=False,
    )
    run(make_client(api, handler).complete(REQ))
    assert sent["max_completion_tokens"] == REQ.max_tokens
    assert "max_tokens" not in sent
    assert "temperature" not in sent
    assert "provider" not in sent  # extra_body vacío: el campo `provider` es de OpenRouter


def test_token_param_rejects_unknown_names(make_api):
    with pytest.raises(ValueError):
        make_api(token_param="max_output_tokens")