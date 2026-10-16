"""Cliente para cualquier servidor compatible con la API de OpenAI.

Sirve igual para OpenRouter, vLLM, Ollama (`/v1`) o llama.cpp server. Se usa
httpx directo en lugar de un SDK para controlar retries, timeouts y qué se
registra, y porque es la misma dependencia que ya usa la API.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import httpx

from .config import DestinationSettings
from .errors import LLMRequestError, LLMResponseError, LLMTransportError
from .schemas import LLMRequest, LLMResult, ToolCall, Usage

_DEBUG_HTTP = os.getenv("LLM_DEBUG_HTTP", "").lower() in ("1", "true", "yes")
"""Solo para depurar con datos ficticios: imprime en stderr el cuerpo del error del proveedor
(puede repetir el prompt) y la forma del request (sin el texto de los mensajes)."""

LAST_FAILED: dict[str, Any] = {}
"""Con LLM_DEBUG_HTTP: el último request rechazado (cuerpo completo) y la respuesta. Lo usa
`python -m app.evalkit.diagnose --caso` para repetirlo con variantes."""

_RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 8.0
_RETRY_AFTER_CAP_S = 30.0

Sleep = Callable[[float], Awaitable[None]]


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: DestinationSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._rng = rng or random.Random()
        headers = {"Content-Type": "application/json"}
        if settings.api_key is not None:
            headers["Authorization"] = f"Bearer {settings.api_key.get_secret_value()}"
        self._http = httpx.AsyncClient(
            base_url=str(settings.base_url).rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(settings.timeout_s, connect=10.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete(self, request: LLMRequest) -> LLMResult:
        body = self._build_body(request)
        started = time.perf_counter()
        attempts = 0
        last_status: int | None = None
        last_error = ""

        while True:
            attempts += 1
            try:
                response = await self._http.post("/chat/completions", json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_status, last_error = None, type(exc).__name__
                retry_after = None
            else:
                if response.status_code < 400:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    return self._parse(response, latency_ms=latency_ms, attempts=attempts)
                last_status = response.status_code
                last_error = _error_summary(response)
                if _DEBUG_HTTP:
                    _debug_dump(body, response)
                    LAST_FAILED.clear()
                    LAST_FAILED.update(
                        {"body": body, "status": response.status_code, "response": response.text[:4000]}
                    )
                if response.status_code not in _RETRY_STATUS:
                    raise LLMRequestError(last_error, status_code=response.status_code)
                retry_after = _retry_after_s(response)

            if attempts > self._settings.max_retries:
                raise LLMTransportError(
                    f"sin respuesta válida tras {attempts} intentos: {last_error}",
                    status_code=last_status,
                    attempts=attempts,
                )
            await self._sleep(self._backoff(attempts, retry_after))

    # ------------------------------------------------------------------ internos

    def _build_body(self, request: LLMRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            **self._settings.extra_body,
            "model": request.model,
            "messages": [m.to_openai() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            body["tools"] = [t.to_openai() for t in request.tools]
        if request.json_mode and self._settings.json_mode and not request.tools:
            body["response_format"] = {"type": "json_object"}
        return body

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, _RETRY_AFTER_CAP_S)
        # Full jitter: evita que varias peticiones reintenten al mismo tiempo.
        return self._rng.uniform(0, min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1)))

    @staticmethod
    def _parse(response: httpx.Response, *, latency_ms: int, attempts: int) -> LLMResult:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError("respuesta que no es JSON") from exc
        if not isinstance(data, dict):
            raise LLMResponseError("respuesta JSON que no es un objeto")
        # Algunos proveedores devuelven HTTP 200 con un objeto de error dentro.
        if isinstance(data.get("error"), dict):
            raise LLMResponseError(f"error del proveedor en respuesta 200: {data['error'].get('code')}")
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(f"respuesta sin choices[0].message ({type(exc).__name__})") from exc

        try:
            tool_calls = tuple(ToolCall.from_openai(tc) for tc in message.get("tool_calls") or ())
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMResponseError(f"tool_call malformada ({type(exc).__name__})") from exc

        usage_raw = data.get("usage") or {}
        details = usage_raw.get("completion_tokens_details") or {}
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else 0
        return LLMResult(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                input_tokens=int(usage_raw.get("prompt_tokens") or 0),
                output_tokens=int(usage_raw.get("completion_tokens") or 0),
                reasoning_tokens=int(reasoning or 0),
                reported_cost_usd=_decimal_or_none(usage_raw.get("cost")),
            ),
            model=str(data.get("model") or ""),
            provider=data.get("provider"),
            latency_ms=latency_ms,
            attempts=attempts,
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    """`usage.cost` de OpenRouter. Cualquier otra cosa (ausente, texto raro) = no reportado."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        out = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return out if out.is_finite() and out >= 0 else None


def _debug_dump(body: dict[str, Any], response: httpx.Response) -> None:
    msgs = body.get("messages", [])
    shape = {k: v for k, v in body.items() if k not in ("messages", "tools")}
    shape["messages"] = f"{len(msgs)} mensajes, {sum(len(str(m.get('content') or '')) for m in msgs)} caracteres"
    print(
        f"[LLM_DEBUG_HTTP] {response.request.method} {response.request.url} -> HTTP {response.status_code}\n"
        f"  request: {json.dumps(shape, ensure_ascii=False, default=str)}\n"
        f"  response: {response.text[:2000]}",
        file=sys.stderr,
    )


def _error_summary(response: httpx.Response) -> str:
    """Estado y código de error, sin el texto libre del proveedor (puede repetir el prompt)."""
    code: Any = None
    try:
        err = response.json().get("error")
        if isinstance(err, dict):
            code = err.get("code") or err.get("type")
    except ValueError:
        pass
    return f"HTTP {response.status_code}" + (f" ({code})" if code else "")


def _retry_after_s(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
