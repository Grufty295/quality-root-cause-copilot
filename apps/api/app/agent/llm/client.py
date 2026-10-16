"""Contrato del cliente LLM.

El agente y el gateway dependen de este Protocol, no de una implementación.
En producción y desarrollo la implementación es `OpenAICompatibleClient`;
en pruebas, un doble que devuelve respuestas guionadas.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .schemas import LLMRequest, LLMResult


@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResult: ...

    async def aclose(self) -> None: ...
