"""Dobles de prueba de la capa LLM. Solo existen en tests/: no hay modo mock en el producto."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.agent.llm import LLMCallRecord, LLMError, LLMRequest, LLMResult, Usage
from app.confidentiality.redactor import RedactionResult

Responder = Callable[[LLMRequest], "LLMResult | LLMError"]


class ScriptedLLMClient:
    """Devuelve respuestas guionadas en orden y guarda cada request recibido."""

    def __init__(
        self, *responses: str | LLMResult | LLMError, model: str = "fake"
    ) -> None:
        self._responses = list(responses)
        self._model = model
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("ScriptedLLMClient: no quedan respuestas guionadas")
        item = self._responses.pop(0)
        if isinstance(item, LLMError):
            raise item
        if isinstance(item, LLMResult):
            return item
        return LLMResult(
            content=item,
            usage=Usage(input_tokens=100, output_tokens=20),
            model=request.model,
            latency_ms=5,
        )

    async def aclose(self) -> None:
        return None


class PassthroughRedactor:
    """No redacta nada. Solo para pruebas del inspector, que debe atrapar lo que el redactor deje pasar."""

    def redact(self, ncr_id: UUID, texts: Sequence[str], *, only: frozenset[str] | None = None) -> RedactionResult:
        return RedactionResult(tuple(texts))

    def restore(
        self, ncr_id: UUID, texts: Sequence[str], *, json_escaped: bool = False
    ) -> list[str]:
        return list(texts)


class MemoryAuditSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[LLMCallRecord] = []
        self._fail = fail

    async def record(self, entry: LLMCallRecord) -> None:
        if self._fail:
            raise RuntimeError("audit_log no disponible")
        self.records.append(entry)


def openai_body(content: Any = "ok", **extra: Any) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "model": extra.pop("model", "m"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        **extra,
    }
