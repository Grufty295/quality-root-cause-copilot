"""El diagnóstico aísla el parámetro que rompe la llamada (transporte en memoria, sin red)."""

from __future__ import annotations

import asyncio
import json

import httpx

from app.agent.llm import config
from app.evalkit import diagnose as d


def _env(monkeypatch, extra):
    for k, v in {
        "LLM_ALLOW_SIMULATED_LOCAL": "true",
        "LLM_LOCAL__SIMULATED": "true",
        "LLM_LOCAL__BASE_URL": "https://openrouter.ai/api/v1",
        "LLM_LOCAL__API_KEY": "sk-or-v1-abcdefghijklmnop1234",
        "LLM_LOCAL__PROVIDER_LABEL": "or",
        "LLM_LOCAL__MODEL_SMALL": "qwen/qwen3.8-27b",
        "LLM_LOCAL__MODEL_LARGE": "qwen/qwen3.8-27b",
        "LLM_LOCAL__EXTRA_BODY": json.dumps(extra),
    }.items():
        monkeypatch.setenv(k, v)
    config.get_llm_settings.cache_clear()


def test_matrix_points_at_the_breaking_parameter(monkeypatch, capsys):
    _env(
        monkeypatch,
        {"provider": {"data_collection": "deny"}, "reasoning": {"effort": "low"}},
    )
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/key"):
            return httpx.Response(
                200, json={"data": {"label": "k", "usage": 0.1, "limit": None}}
            )
        if req.url.path.endswith("/endpoints"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "endpoints": [
                            {
                                "provider_name": "DeepInfra",
                                "tag": "deepinfra",
                                "quantization": "fp8",
                                "context_length": 262144,
                                "max_completion_tokens": 4096,
                                "supported_parameters": ["max_tokens"],
                            }
                        ]
                    }
                },
            )
        body = json.loads(req.content)
        sent.append(body)
        if "reasoning" in body:
            return httpx.Response(
                400, json={"error": {"code": 400, "message": "reasoning not supported"}}
            )
        if body["max_tokens"] > 4096:
            return httpx.Response(
                400, json={"error": {"code": 400, "message": "max_tokens too large"}}
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                "provider": "DeepInfra",
            },
        )

    code = asyncio.run(d.diagnose("local", transport=httpx.MockTransport(handler)))
    out = capsys.readouterr().out
    config.get_llm_settings.cache_clear()
    assert code == 1
    assert (
        "sk-or-v1-abcdefghijklmnop1234" not in out and "…1234" in out
    )  # nunca la key completa
    assert "slug=deepinfra" in out and "reasoning=no" in out
    assert (
        "FALLA  qwen/qwen3.8-27b · configuración real" in out
        and "reasoning not supported" in out
    )
    assert "ok     qwen/qwen3.8-27b · sin `reasoning`" in out
    assert (
        "max_tokens too large" in out
    )  # la variante como el agente también falla, por otro motivo
    assert len({json.dumps(b, sort_keys=True) for b in sent}) == len(
        sent
    )  # cada variante distinta


def test_missing_key_is_reported(monkeypatch, capsys):
    _env(monkeypatch, {})
    monkeypatch.setenv("LLM_LOCAL__API_KEY", "")
    config.get_llm_settings.cache_clear()

    def handler(req):
        return httpx.Response(
            401, json={"error": {"code": 401, "message": "No auth credentials found"}}
        )

    asyncio.run(d.diagnose("local", transport=httpx.MockTransport(handler)))
    out = capsys.readouterr().out
    config.get_llm_settings.cache_clear()
    assert "VACÍA" in out and "HTTP 401" in out


def test_replay_variants_separate_parameters_provider_and_content():
    body = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "s" * 10},
            {"role": "user", "content": "u" * 9000},
        ],
        "max_tokens": 8192,
        "provider": {"data_collection": "deny"},
        "reasoning": {"effort": "low"},
    }
    vs = dict(d.replay_variants(body, "Alibaba"))
    assert "reasoning" not in vs["sin `reasoning`"]
    assert vs["ignorando al proveedor Alibaba"]["provider"] == {
        "data_collection": "deny",
        "ignore": ["Alibaba"],
    }
    assert vs["mismos parámetros, mensaje trivial"]["messages"] == [
        {"role": "system", "content": "Responde solo: ok"}
    ]
    cut = vs["último mensaje recortado a 3000 caracteres"]["messages"]
    assert len(cut[-1]["content"]) == 3000 and cut[0]["content"] == "s" * 10
    assert body["max_tokens"] == 8192  # las variantes no modifican el original
