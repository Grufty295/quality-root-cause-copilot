"""DTOs de la capa LLM.

Todos son inmutables (`frozen`) y rechazan campos desconocidos (`extra="forbid"`):
un DTO que acepta cualquier cosa no documenta ni protege nada.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ConfidentialityLevel, Destination, ModelTier, Stage


class _DTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- mensajes


class ToolCall(_DTO):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]

    @classmethod
    def from_openai(cls, raw: dict[str, Any]) -> ToolCall:
        fn = raw["function"]
        args = fn.get("arguments") or "{}"
        return cls(id=raw["id"], name=fn["name"], arguments=json.loads(args) if isinstance(args, str) else args)

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)},
        }


class Message(_DTO):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Message:
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("un mensaje 'tool' requiere tool_call_id")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("solo 'assistant' puede llevar tool_calls")
        if self.content is None and not self.tool_calls:
            raise ValueError("el mensaje necesita content o tool_calls")
        return self

    def to_openai(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [tc.to_openai() for tc in self.tool_calls]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        return out


class ToolSpec(_DTO):
    """Descripción de una tool para el modelo. Los parámetros salen de un modelo Pydantic."""

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = Field(min_length=1)
    parameters: dict[str, Any]

    @classmethod
    def from_model(cls, name: str, description: str, params: type[BaseModel]) -> ToolSpec:
        return cls(name=name, description=description, parameters=params.model_json_schema())

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


# --------------------------------------------------------------------------- request / result


class LLMRequest(_DTO):
    """Lo que el cliente envía. El modelo concreto lo decide el router, no quien llama."""

    model: str = Field(min_length=1)
    messages: tuple[Message, ...] = Field(min_length=1)
    tools: tuple[ToolSpec, ...] = ()
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0, le=32_000)
    json_mode: bool = False


class Usage(_DTO):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    """Parte de `output_tokens` que fue razonamiento (se cobra, no se ve)."""
    reported_cost_usd: Decimal | None = None
    """Costo que reporta el proveedor (OpenRouter `usage.cost`). None si no lo reporta."""

    def __add__(self, other: Usage) -> Usage:
        costs = [c for c in (self.reported_cost_usd, other.reported_cost_usd) if c is not None]
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            reported_cost_usd=sum(costs, Decimal(0)) if costs else None,
        )


class LLMResult(_DTO):
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: Usage = Usage()
    model: str
    """Modelo que reporta la respuesta (puede diferir del pedido, p. ej. un alias)."""
    provider: str | None = None
    """Proveedor subyacente si la API lo informa (OpenRouter lo hace)."""
    latency_ms: int = Field(ge=0)
    attempts: int = Field(default=1, ge=1)


# --------------------------------------------------------------------------- routing


class RouteContext(_DTO):
    """Todo lo que el router necesita saber del contexto que va a salir.

    `input_level` es el nivel de la NCR (`ncr.detected_level`); `None` = sin clasificar.
    `fragment_levels` son los niveles de los fragmentos recuperados que irán en el prompt.
    """

    stage: Stage
    input_level: ConfidentialityLevel | None
    input_contains_pii: bool
    fragment_ids: tuple[UUID, ...] = ()
    fragment_levels: tuple[ConfidentialityLevel, ...] = ()
    fragment_contains_pii: bool = False
    tier: ModelTier | None = None
    """Fuerza el tamaño del modelo. Sin esto lo decide la etapa. Lo usa la cascada de D4
    (empezar con el pequeño y escalar). No cambia el destino: eso sigue siendo del nivel."""

    @model_validator(mode="after")
    def _ids_match_levels(self) -> RouteContext:
        if len(self.fragment_ids) != len(self.fragment_levels):
            raise ValueError("fragment_ids y fragment_levels deben tener la misma longitud")
        return self

    @property
    def level(self) -> ConfidentialityLevel:
        return ConfidentialityLevel.highest((self.input_level, *self.fragment_levels))

    @property
    def contains_pii(self) -> bool:
        return self.input_contains_pii or self.fragment_contains_pii


class RouteDecision(_DTO):
    destination: Destination
    level: ConfidentialityLevel
    tier: ModelTier
    model: str
    simulated: bool
    must_redact: bool
    """Identificadores de cliente y números de parte deben reemplazarse antes de enviar."""
    must_pseudonymize: bool
    """Hay PII: se pseudonimiza hacia cualquier destino, también el local."""
    reason: str

    @model_validator(mode="after")
    def _invariant(self) -> RouteDecision:
        # Misma regla que el CHECK de audit_log: nunca confidencial hacia la API.
        if self.level is ConfidentialityLevel.CONFIDENCIAL and self.destination is Destination.API:
            raise ValueError("violación de política: contexto confidencial hacia destino api")
        return self


# --------------------------------------------------------------------------- auditoría


class LLMCallRecord(_DTO):
    """Una fila de `audit_log`. Nunca lleva contenido: solo metadatos e IDs.

    Lo construye el gateway y lo persiste el repositorio de auditoría.
    """

    user_id: UUID
    ncr_id: UUID
    stage: Stage
    detected_level: ConfidentialityLevel
    destination: Destination
    provider: str
    model: str
    fragment_ids: tuple[UUID, ...]
    redacted: bool
    pseudonymized: bool
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    """Incluye `outcome` (ok, error, blocked) y, si falló, `error` con tipo y estado.

    Van en tags y no en columnas propias para no cambiar la serialización
    canónica que alimenta el hash encadenado de audit_log.
    """

    @field_validator("tags")
    @classmethod
    def _short_tag_values(cls, v: dict[str, str]) -> dict[str, str]:
        if any(len(k) > 64 or len(val) > 200 for k, val in v.items()):
            raise ValueError("tags demasiado largos: no deben llevar contenido")
        return v

    @model_validator(mode="after")
    def _invariant(self) -> LLMCallRecord:
        if self.detected_level is ConfidentialityLevel.CONFIDENCIAL and self.destination is Destination.API:
            raise ValueError("violación de política: contexto confidencial hacia destino api")
        return self
