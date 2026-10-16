"""Salida estructurada sin depender de `response_format` del proveedor.

No todos los modelos de OpenRouter, vLLM u Ollama soportan JSON Schema nativo
de la misma forma. Aquí el esquema va en el prompt, la respuesta se valida con
Pydantic y, si falla, se reintenta mostrando al modelo el error de validación.
Cada intento es una llamada independiente (y una fila de auditoría): por eso
este módulo recibe la función que llama al modelo en lugar de un cliente.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import StructuredOutputError
from .schemas import LLMResult, Message, Usage

T = TypeVar("T", bound=BaseModel)

CallModel = Callable[[tuple[Message, ...]], Awaitable[LLMResult]]

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_MAX_ERROR_CHARS = 1500


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T
    attempts: int
    usage: Usage
    results: tuple[LLMResult, ...] = field(repr=False)


def schema_instruction(schema: type[BaseModel]) -> Message:
    return Message(
        role="system",
        content=(
            "Responde únicamente con un objeto JSON válido, sin texto antes ni después "
            "y sin bloques de código, que cumpla este JSON Schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        ),
    )


def parse_structured(raw: str | None, schema: type[T]) -> T:
    """Extrae y valida. Lanza ValueError o ValidationError con un mensaje útil para el modelo."""
    if raw is None or not raw.strip():
        raise ValueError("la respuesta está vacía")
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    return schema.model_validate_json(text)


async def complete_structured(
    call: CallModel,
    messages: tuple[Message, ...],
    schema: type[T],
    *,
    max_attempts: int = 3,
) -> StructuredResult[T]:
    if max_attempts < 1:
        raise ValueError("max_attempts debe ser >= 1")

    convo: tuple[Message, ...] = (schema_instruction(schema), *messages)
    results: list[LLMResult] = []
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        result = await call(convo)
        results.append(result)
        try:
            value = parse_structured(result.content, schema)
        except (ValueError, ValidationError) as exc:
            last_error = _describe(exc)
            convo = (
                *convo,
                Message(role="assistant", content=result.content or "(vacío)"),
                Message(
                    role="user",
                    content=(
                        "Tu respuesta no cumple el esquema. Corrige solo estos errores y "
                        f"responde de nuevo únicamente con el JSON:\n{last_error}"
                    ),
                ),
            )
            continue
        usage = sum((r.usage for r in results), Usage())
        return StructuredResult(value=value, attempts=attempt, usage=usage, results=tuple(results))

    raise StructuredOutputError(
        f"salida inválida para {schema.__name__} tras {max_attempts} intentos",
        attempts=max_attempts,
        last_error=last_error,
    )


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        lines = [
            f"- {'.'.join(str(p) for p in err['loc']) or '(raíz)'}: {err['msg']}"
            for err in exc.errors(include_url=False, include_input=False)
        ]
        text = "\n".join(lines)
    else:
        text = str(exc)
    return text[:_MAX_ERROR_CHARS]
