"""El juez de los evals semánticos, sobre el mismo `ModelGateway` del agente.

DeepEval y Ragas traen sus propios clientes (OpenAI por defecto). No se usan: el juez lee
fragmentos y evidencia del caso, que pueden ser confidenciales, y debe obedecer la misma regla
que el agente (lo confidencial se juzga en local, lo demás puede ir a la API ya redactado) y
quedar en `audit_log`. Por eso los dos frameworks reciben un adaptador que llama al gateway:

* `DeepEvalGatewayModel` implementa `DeepEvalBaseLLM` (`a_generate(prompt, schema)`).
* `RagasGatewayLLM` implementa `InstructorBaseRagasLLM` (`agenerate(prompt, response_model)`).

Los dos comparten `GatewayJudge`, que arma el `RouteContext` con el nivel más alto de la
evidencia que se juzga, cuenta llamadas y corta al llegar al tope (`JudgeBudgetExceeded`):
un experimento no puede gastar sin límite.

La telemetría de los frameworks se apaga al importarlos (`quiet_frameworks`): DeepEval y Ragas
mandan eventos de uso a sus servidores por defecto.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.agent.llm import (
    CallMeta,
    ConfidentialityLevel,
    Message,
    ModelGateway,
    RouteContext,
    Stage,
)

T = TypeVar("T", bound=BaseModel)


def quiet_frameworks() -> None:
    """Sin telemetría ni subida de resultados a servicios externos. Llamar antes de importar."""
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
    os.environ.setdefault("DEEPEVAL_UPDATE_WARNING_OPT_IN", "0")
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    # Sin clave de Confident AI, DeepEval no sube nada; se borra por si el entorno la trae.
    os.environ.pop("CONFIDENT_API_KEY", None)


class JudgeBudgetExceeded(RuntimeError):
    pass


@dataclass
class JudgeBudget:
    max_calls: int
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def take(self) -> None:
        async with self._lock:
            if self.calls >= self.max_calls:
                raise JudgeBudgetExceeded(
                    f"el juez llegó al tope de {self.max_calls} llamadas"
                )
            self.calls += 1


@dataclass(frozen=True)
class JudgeScope:
    """A qué corrida pertenece lo que se juzga: sale en `audit_log` con etapa `eval`."""

    user_id: UUID
    ncr_id: UUID
    run_id: str | None
    level: ConfidentialityLevel
    contains_pii: bool
    feature: str = "eval_juez"


class GatewayJudge:
    def __init__(
        self, gateway: ModelGateway, scope: JudgeScope, budget: JudgeBudget
    ) -> None:
        self._gw, self.scope, self._budget = gateway, scope, budget
        self.model_name = "gateway"

    def _meta(self) -> CallMeta:
        return CallMeta(
            user_id=self.scope.user_id,
            ncr_id=self.scope.ncr_id,
            trace_id=self.scope.run_id,
            tags={"feature": self.scope.feature, "entorno": "eval"},
        )

    def _ctx(self) -> RouteContext:
        return RouteContext(
            stage=Stage.EVAL,
            input_level=self.scope.level,
            input_contains_pii=self.scope.contains_pii,
        )

    def route(self):
        return self._gw.route(self._ctx())

    async def structured(self, prompt: str, schema: type[T]) -> T:
        await self._budget.take()
        res = await self._gw.complete_structured(
            self._meta(),
            self._ctx(),
            (Message(role="user", content=prompt),),
            schema,
            max_tokens=4096,
        )
        u = res.output.usage
        self._budget.tokens_in += u.input_tokens
        self._budget.tokens_out += u.output_tokens
        self.model_name = res.decision.model
        return res.output.value

    async def text(self, prompt: str) -> str:
        await self._budget.take()
        res = await self._gw.complete(
            self._meta(),
            self._ctx(),
            (Message(role="user", content=prompt),),
            max_tokens=2048,
        )
        u = res.result.usage
        self._budget.tokens_in += u.input_tokens
        self._budget.tokens_out += u.output_tokens
        self.model_name = res.decision.model
        return res.result.content or ""


def scope_for(
    row: dict[str, Any], evidence_ids: Sequence[str], run_id: str | None = None
) -> JudgeScope:
    """Nivel = el más alto de la evidencia que va al juez (sin dato = confidencial)."""
    ev = row.get("evidencia") or {}
    levels = [
        ConfidentialityLevel(ev[i]["nivel"])
        for i in evidence_ids
        if i in ev and ev[i].get("nivel")
    ]
    level = (
        ConfidentialityLevel.highest(levels)
        if levels
        else ConfidentialityLevel.CONFIDENCIAL
    )
    return JudgeScope(
        user_id=UUID(row["user_id"]),
        ncr_id=UUID(row["ncr_id"]),
        run_id=run_id or row.get("run_id"),
        level=level,
        contains_pii=any(ev[i].get("pii") for i in evidence_ids if i in ev),
    )


# --------------------------------------------------------------------------- adaptadores


def deepeval_model(judge: GatewayJudge):
    """Un `DeepEvalBaseLLM` sobre el gateway. Se define dentro para que DeepEval sea opcional."""
    quiet_frameworks()
    from deepeval.models import DeepEvalBaseLLM

    class DeepEvalGatewayModel(DeepEvalBaseLLM):
        def __init__(self) -> None:
            self._judge = judge
            super().__init__(model="gateway")

        def load_model(self, *args: Any, **kwargs: Any) -> Any:
            return self._judge

        def get_model_name(self, *args: Any, **kwargs: Any) -> str:
            return f"gateway:{self._judge.model_name}"

        async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
            if schema is not None:
                return await self._judge.structured(prompt, schema)
            return await self._judge.text(prompt)

        def generate(self, prompt: str, schema: type[BaseModel] | None = None):
            return asyncio.run(self.a_generate(prompt, schema))

    return DeepEvalGatewayModel()


def ragas_llm(judge: GatewayJudge):
    """Un `InstructorBaseRagasLLM` sobre el gateway (métricas `ragas.metrics.collections`)."""
    quiet_frameworks()
    from ragas.llms.base import InstructorBaseRagasLLM

    class RagasGatewayLLM(InstructorBaseRagasLLM):
        def __init__(self) -> None:
            self._judge = judge

        async def agenerate(self, prompt: str, response_model: type[T]) -> T:
            return await self._judge.structured(prompt, response_model)

        def generate(self, prompt: str, response_model: type[T]) -> T:
            return asyncio.run(self.agenerate(prompt, response_model))

    return RagasGatewayLLM()
