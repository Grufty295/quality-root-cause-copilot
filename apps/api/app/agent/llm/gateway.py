"""Gateway de modelos: el único punto por el que el agente llama a un LLM.

Por cada llamada:

1. el router decide destino y modelo a partir del contexto;
2. si el destino es api, el redactor reemplaza clientes, partes y PII por marcadores
   y el inspector revisa el payload ya redactado: bloquea cualquier fuga;
3. se llama al cliente del destino;
4. la respuesta vuelve con los marcadores restaurados a sus valores reales;
5. se registra una fila de auditoría (también si falló o se bloqueó).

Si la auditoría no se puede escribir, el resultado no se devuelve: una salida
del modelo sin registro no debe llegar a un 8D.

Los nodos del grafo reciben este gateway, nunca un `LLMClient` directo.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.confidentiality.redactor import PII_TYPES, Redactor

from .client import LLMClient
from .config import LLMSettings
from .enums import Destination
from .errors import (
    LLMError,
    LLMRequestError,
    LLMTransportError,
    PolicyViolation,
    RedactionFailed,
)
from .inspector import PayloadInspector
from .router import ConfidentialityRouter
from .schemas import (
    LLMCallRecord,
    LLMRequest,
    LLMResult,
    Message,
    RouteContext,
    RouteDecision,
    ToolSpec,
)
from .structured import StructuredResult, complete_structured

T = TypeVar("T", bound=BaseModel)


class AuditSink(Protocol):
    """Lo implementa el repositorio de auditoría (INSERT en audit_log)."""

    async def record(self, entry: LLMCallRecord) -> None: ...


class CallMeta(BaseModel):
    """Quién y para qué. Viene del servidor (sesión y NCR), nunca del LLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    ncr_id: UUID
    trace_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    """Tags de FinOps: planta, línea, feature, entorno."""


@dataclass(frozen=True)
class GatewayResult:
    decision: RouteDecision
    result: LLMResult


@dataclass(frozen=True)
class GatewayStructuredResult(Generic[T]):
    decision: RouteDecision
    output: StructuredResult[T]


class ModelGateway:
    def __init__(
        self,
        settings: LLMSettings,
        clients: Mapping[Destination, LLMClient],
        audit: AuditSink,
        inspector: PayloadInspector | None,
        redactor: Redactor | None = None,
    ) -> None:
        if Destination.LOCAL not in clients:
            raise ValueError("falta el cliente del destino local")
        if settings.api is not None:
            if Destination.API not in clients:
                raise ValueError("destino api configurado sin cliente")
            if inspector is None:
                raise ValueError("el destino api requiere un inspector de payloads")
            if redactor is None:
                raise ValueError("el destino api requiere un redactor")
        self._settings = settings
        self._router = ConfidentialityRouter(settings)
        self._clients = dict(clients)
        self._audit = audit
        self._inspector = inspector
        self._redactor = redactor

    @property
    def settings(self) -> LLMSettings:
        """Configuración efectiva (solo lectura): la usa el manifiesto de cada corrida."""
        return self._settings

    def route(self, ctx: RouteContext) -> RouteDecision:
        return self._router.decide(ctx)

    async def complete(
        self,
        meta: CallMeta,
        ctx: RouteContext,
        messages: tuple[Message, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> GatewayResult:
        decision = self.route(ctx)
        result = await self._call(
            meta,
            ctx,
            decision,
            messages,
            tools,
            temperature,
            max_tokens,
            json_mode=False,
        )
        return GatewayResult(decision=decision, result=result)

    async def complete_structured(
        self,
        meta: CallMeta,
        ctx: RouteContext,
        messages: tuple[Message, ...],
        schema: type[T],
        *,
        max_attempts: int = 3,
        temperature: float = 0.0,
        # Los modelos con razonamiento cuentan esos tokens dentro del tope: con 4096 un D4
        # completo se cortaba a media respuesta y el reintento pagaba la llamada dos veces.
        max_tokens: int = 8192,
    ) -> GatewayStructuredResult[T]:
        decision = self.route(ctx)

        async def call(convo: tuple[Message, ...]) -> LLMResult:
            return await self._call(
                meta, ctx, decision, convo, (), temperature, max_tokens, json_mode=True
            )

        output = await complete_structured(
            call, messages, schema, max_attempts=max_attempts
        )
        return GatewayStructuredResult(decision=decision, output=output)

    # ------------------------------------------------------------------ internos

    async def _call(
        self,
        meta: CallMeta,
        ctx: RouteContext,
        decision: RouteDecision,
        messages: tuple[Message, ...],
        tools: tuple[ToolSpec, ...],
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool,
    ) -> LLMResult:
        redactions: dict[str, int] = {}
        outgoing = messages
        to_api = decision.destination is Destination.API
        # api: todo identificador; local con PII: solo PII (RouteDecision.must_pseudonymize).
        redact_scope = None if to_api else PII_TYPES
        if to_api or decision.must_pseudonymize:
            try:
                if self._redactor is None:
                    raise RuntimeError("sin redactor")
                outgoing, redactions = await self._redact(meta, messages, redact_scope)
            except Exception as exc:
                # Sin redacción no se envía. Solo el tipo de error: nada del contenido.
                error: LLMError = RedactionFailed(
                    f"redaccion fallida: {type(exc).__name__}"
                )
                await self._audit.record(
                    self._record(meta, ctx, decision, None, error=error)
                )
                raise error from exc
        if to_api:
            assert self._inspector is not None  # garantizado en __init__
            found = self._inspector.findings(outgoing)
            if found:
                error = PolicyViolation(
                    f"payload hacia api con identificadores confidenciales: {sorted(set(found))}"
                )
                await self._audit.record(
                    self._record(
                        meta, ctx, decision, None, error=error, redactions=redactions
                    )
                )
                raise error

        request = LLMRequest(
            model=decision.model,
            messages=outgoing,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        try:
            result = await self._clients[decision.destination].complete(request)
        except LLMError as exc:
            await self._audit.record(
                self._record(
                    meta, ctx, decision, None, error=exc, redactions=redactions
                )
            )
            raise

        if to_api or decision.must_pseudonymize:
            result = await self._restore(meta, result, json_mode=json_mode)

        await self._audit.record(
            self._record(meta, ctx, decision, result, redactions=redactions)
        )
        return result

    async def _redact(
        self, meta: CallMeta, messages: tuple[Message, ...], only: frozenset[str] | None
    ) -> tuple[tuple[Message, ...], dict[str, int]]:
        redactor = self._redactor
        assert redactor is not None
        slots = _string_slots(messages)
        result = await asyncio.to_thread(
            lambda: redactor.redact(meta.ncr_id, [text for _, text in slots], only=only)
        )
        return _apply_slots(messages, slots, result.texts), dict(result.counts)

    async def _restore(
        self, meta: CallMeta, result: LLMResult, *, json_mode: bool
    ) -> LLMResult:
        """Devuelve a los valores reales lo que el modelo escribió con marcadores."""
        assert self._redactor is not None
        texts = [result.content] if result.content else []
        for tc in result.tool_calls:
            texts.append(json.dumps(tc.arguments, ensure_ascii=False))
        if not texts:
            return result
        restored = await asyncio.to_thread(
            self._redactor.restore, meta.ncr_id, texts, json_escaped=json_mode
        )
        content = restored.pop(0) if result.content else result.content
        calls = tuple(
            tc.model_copy(update={"arguments": json.loads(text)})
            for tc, text in zip(result.tool_calls, restored, strict=True)
        )
        return result.model_copy(update={"content": content, "tool_calls": calls})

    def _record(
        self,
        meta: CallMeta,
        ctx: RouteContext,
        decision: RouteDecision,
        result: LLMResult | None,
        *,
        error: LLMError | None = None,
        redactions: Mapping[str, int] | None = None,
    ) -> LLMCallRecord:
        dest = self._settings.destination(decision.destination)
        provider = dest.provider_label
        if result is not None and result.provider:
            provider = f"{provider}:{result.provider}"
        if decision.simulated:
            provider = f"{provider} (simulado)"

        tags = {
            **meta.tags,
            "stage": ctx.stage.value,
            "destination": decision.destination.value,
            "tier": decision.tier.value,
            "simulated": str(decision.simulated).lower(),
        }
        if result is not None and result.model and result.model != decision.model:
            tags["reported_model"] = result.model[:120]
        if result is not None and result.usage.reasoning_tokens:
            tags["reasoning_tokens"] = str(result.usage.reasoning_tokens)
        if result is not None and result.finish_reason:
            # "length" = se cortó por max_tokens: un JSON roto por eso no es un error del esquema.
            tags["finish_reason"] = str(result.finish_reason)[:40]
        if result is not None and result.usage.reported_cost_usd is not None:
            # El costo real del proveedor, junto al estimado por tabla de precios (cost_usd).
            tags["reported_cost_usd"] = str(result.usage.reported_cost_usd)
        if result is not None and result.attempts > 1:
            tags["http_attempts"] = str(result.attempts)
        if redactions:
            # Solo tipos y conteos: sirve para medir cuánto se redacta sin guardar valores.
            tags["redactions"] = ",".join(
                f"{k}={v}" for k, v in sorted(redactions.items())
            )
        if error is None:
            tags["outcome"] = "ok"
        else:
            tags["outcome"] = (
                "blocked" if isinstance(error, PolicyViolation) else "error"
            )
            tags["error"] = _error_label(error)

        input_tokens = result.usage.input_tokens if result else 0
        output_tokens = result.usage.output_tokens if result else 0
        return LLMCallRecord(
            user_id=meta.user_id,
            ncr_id=meta.ncr_id,
            stage=ctx.stage,
            detected_level=decision.level,
            destination=decision.destination,
            provider=provider[:120],
            model=decision.model,
            fragment_ids=ctx.fragment_ids,
            redacted=decision.must_redact,
            pseudonymized=decision.must_pseudonymize,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=dest.cost_usd(input_tokens, output_tokens)
            if result
            else Decimal("0"),
            latency_ms=result.latency_ms if result else 0,
            trace_id=meta.trace_id,
            tags=tags,
        )


def _error_label(error: LLMError) -> str:
    """Tipo y estado, sin texto libre: el audit log nunca guarda contenido."""
    status = getattr(error, "status_code", None)
    if isinstance(error, (LLMTransportError, LLMRequestError)) and status is not None:
        return f"{type(error).__name__}: HTTP {status}"
    if isinstance(error, PolicyViolation):
        return str(error)  # solo lista tipos de entidad, nunca valores
    return type(error).__name__


# Un "slot" es un texto que sale en el payload: el contenido de un mensaje o un
# argumento de tool call. Se redactan todos juntos para que un mismo valor reciba el
# mismo marcador en todo el payload.
_Slot = tuple[tuple[int, int | None], str]


def _string_slots(messages: tuple[Message, ...]) -> list[_Slot]:
    slots: list[_Slot] = []
    for i, m in enumerate(messages):
        if m.content:
            slots.append(((i, None), m.content))
        for j, tc in enumerate(m.tool_calls):
            slots.append(((i, j), json.dumps(tc.arguments, ensure_ascii=False)))
    return slots


def _apply_slots(
    messages: tuple[Message, ...], slots: list[_Slot], texts: tuple[str, ...]
) -> tuple[Message, ...]:
    out = list(messages)
    for ((i, j), _), text in zip(slots, texts, strict=True):
        m = out[i]
        if j is None:
            out[i] = m.model_copy(update={"content": text})
        else:
            calls = list(m.tool_calls)
            # JSON de los argumentos con los valores ya reemplazados; los marcadores no rompen el JSON.
            calls[j] = calls[j].model_copy(update={"arguments": json.loads(text)})
            out[i] = m.model_copy(update={"tool_calls": tuple(calls)})
    return tuple(out)
