"""Callbacks del agente: qué pasa en cada corrida, sin contenido.

Dos fuentes de eventos, un solo destino (`AgentObserver`):

* **Hooks de LangGraph.** `NodeCallbacks` es un `AsyncCallbackHandler` de LangChain que el
  grafo recibe en `config["callbacks"]`. LangGraph avisa el inicio y el fin de cada nodo
  (`metadata["langgraph_node"]`); de ahí salen las etapas y su duración sin envolver nodos a
  mano. El handler ignora `inputs` y `outputs`: ahí viaja el estado completo (NCR, fragmentos).
* **Eventos de dominio.** Lo que LangGraph no sabe: herramienta rechazada, fragmento en
  cuarentena, escalamiento al modelo grande, cada llamada al LLM, los fragmentos que trajo cada
  búsqueda. Los emite el grafo directo al observador.

Regla de privacidad: el observador recibe identificadores, conteos, tiempos y códigos de
evento, nunca texto. La única excepción es `run_finished`, que recibe el estado final porque
el eval necesita el texto citado para el juez (`RecordingObserver`); un observador que exporta
fuera del proceso (Langfuse) no debe leerlo.

Un observador que falla nunca rompe el análisis: `CompositeObserver` registra el error y sigue.

Por qué no el `CallbackHandler` de Langfuse para LangChain: manda `inputs`/`outputs` de cada
nodo, es decir, el estado con fragmentos confidenciales, a un servicio aparte del gateway y
fuera del `audit_log`. Aquí Langfuse solo recibe lo mismo que ya guarda la auditoría.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedRef:
    """Un fragmento devuelto por una búsqueda, en su orden. Sin contenido."""

    fragment_id: UUID
    source_key: str
    section: str
    rank: int


@dataclass(frozen=True)
class LLMCallEvent:
    stage: str
    tier: str
    model: str
    destination: str
    level: str
    input_tokens: int
    output_tokens: int
    attempts: int
    ok: bool = True
    latency_ms: int = 0
    """Suma de la espera HTTP de los intentos de esta llamada (sin cola local ni reintentos fuera)."""
    reasoning_tokens: int = 0
    """Parte de `output_tokens` que fue razonamiento (se cobra, no se ve)."""
    cost_usd: float | None = None
    """Costo que reporta el proveedor; None si no lo reporta (no se inventa)."""
    finish_reason: str = ""


class AgentObserver:
    """Métodos vacíos: cada observador implementa lo que le sirve."""

    def run_started(
        self, run_id: str, *, ncr_id: UUID, disciplines: Sequence[str]
    ) -> None: ...

    def stage_started(self, run_id: str, stage: str) -> None: ...

    def stage_finished(
        self, run_id: str, stage: str, duration_ms: int, ok: bool
    ) -> None: ...

    def event(self, run_id: str, stage: str, event: str, detail: str) -> None: ...

    def llm_call(self, run_id: str, call: LLMCallEvent) -> None: ...

    def tool_call(
        self, run_id: str, tool: str, duration_ms: int, ok: bool
    ) -> None: ...

    def retrieved(
        self, run_id: str, search: str, refs: Sequence[RetrievedRef]
    ) -> None: ...

    def run_finished(
        self,
        run_id: str,
        *,
        state: Mapping[str, Any] | None,
        duration_ms: int,
        error: str | None,
    ) -> None: ...

    def close(self) -> None: ...


class CompositeObserver(AgentObserver):
    """Reparte cada evento entre varios observadores; un fallo de uno no afecta a los demás."""

    def __init__(self, observers: Iterable[AgentObserver]) -> None:
        self.observers = [o for o in observers if o is not None]

    def _each(self, name: str, *args: Any, **kwargs: Any) -> None:
        for o in self.observers:
            try:
                getattr(o, name)(*args, **kwargs)
            except Exception:
                log.warning(
                    "observador %s falló en %s", type(o).__name__, name, exc_info=True
                )

    def run_started(self, run_id, *, ncr_id, disciplines):
        self._each("run_started", run_id, ncr_id=ncr_id, disciplines=disciplines)

    def stage_started(self, run_id, stage):
        self._each("stage_started", run_id, stage)

    def stage_finished(self, run_id, stage, duration_ms, ok):
        self._each("stage_finished", run_id, stage, duration_ms, ok)

    def event(self, run_id, stage, event, detail):
        self._each("event", run_id, stage, event, detail)

    def llm_call(self, run_id, call):
        self._each("llm_call", run_id, call)

    def tool_call(self, run_id, tool, duration_ms, ok):
        self._each("tool_call", run_id, tool, duration_ms, ok)

    def retrieved(self, run_id, search, refs):
        self._each("retrieved", run_id, search, refs)

    def run_finished(self, run_id, *, state, duration_ms, error):
        self._each(
            "run_finished", run_id, state=state, duration_ms=duration_ms, error=error
        )

    def close(self):
        self._each("close")


# --------------------------------------------------------------------------- hook de LangGraph


class NodeCallbacks(AsyncCallbackHandler):
    """Convierte los callbacks de LangChain/LangGraph en `stage_started`/`stage_finished`.

    Solo cuenta las corridas cuyo nombre es el del nodo (las funciones de las aristas
    condicionales también disparan callbacks, con otro nombre). Ignora entradas y salidas.
    """

    def __init__(self, observer: AgentObserver, run_id: str) -> None:
        self._obs = observer
        self._run_id = run_id
        self._open: dict[UUID, tuple[str, float]] = {}

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if node and kwargs.get("name") == node:
            self._open[run_id] = (node, time.perf_counter())
            self._obs.stage_started(self._run_id, node)

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._close(run_id, ok=True)

    async def on_chain_error(
        self, error: BaseException, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._close(run_id, ok=False)

    def _close(self, run_id: UUID, *, ok: bool) -> None:
        opened = self._open.pop(run_id, None)
        if opened:
            node, t0 = opened
            ms = int((time.perf_counter() - t0) * 1000)
            self._obs.stage_finished(self._run_id, node, ms, ok)


# --------------------------------------------------------------------------- observadores


@dataclass
class RunRecord:
    run_id: str
    ncr_id: UUID | None = None
    disciplines: tuple[str, ...] = ()
    stage_ms: dict[str, int] = field(default_factory=dict)
    stage_ok: dict[str, bool] = field(default_factory=dict)
    events: list[tuple[str, str, str]] = field(default_factory=list)
    llm_calls: list[LLMCallEvent] = field(default_factory=list)
    retrieved: dict[str, list[RetrievedRef]] = field(default_factory=dict)
    tool_ms: dict[str, int] = field(default_factory=dict)
    """Milisegundos por herramienta (suma si se llama más de una vez) y cuántas veces."""
    tool_count: dict[str, int] = field(default_factory=dict)
    duration_ms: int | None = None
    error: str | None = None
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    """id corto (F#/T#) → {texto, nivel, tipo, documento, seccion, fragment_id}. Solo lo llena
    `RecordingObserver(keep_evidence=True)`; es texto del caso y no sale del proceso."""


class RecordingObserver(AgentObserver):
    """Guarda en memoria lo que pasó en cada corrida. Lo usan el servicio (tiempos por etapa en
    `analysis_run`) y el eval (más el texto de la evidencia, para el juez)."""

    def __init__(self, *, keep_evidence: bool = False) -> None:
        self.keep_evidence = keep_evidence
        self.runs: dict[str, RunRecord] = {}

    def _rec(self, run_id: str) -> RunRecord:
        return self.runs.setdefault(run_id, RunRecord(run_id))

    def run_started(self, run_id, *, ncr_id, disciplines):
        r = self._rec(run_id)
        r.ncr_id, r.disciplines = ncr_id, tuple(disciplines)

    def stage_finished(self, run_id, stage, duration_ms, ok):
        r = self._rec(run_id)
        # Un nodo puede correr más de una vez (no hoy, pero LangGraph lo permite): se suma.
        r.stage_ms[stage] = r.stage_ms.get(stage, 0) + duration_ms
        r.stage_ok[stage] = r.stage_ok.get(stage, True) and ok

    def event(self, run_id, stage, event, detail):
        self._rec(run_id).events.append((stage, event, detail))

    def llm_call(self, run_id, call):
        self._rec(run_id).llm_calls.append(call)

    def tool_call(self, run_id, tool, duration_ms, ok):
        r = self._rec(run_id)
        r.tool_ms[tool] = r.tool_ms.get(tool, 0) + duration_ms
        r.tool_count[tool] = r.tool_count.get(tool, 0) + 1

    def retrieved(self, run_id, search, refs):
        self._rec(run_id).retrieved.setdefault(search, []).extend(refs)

    def run_finished(self, run_id, *, state, duration_ms, error):
        r = self._rec(run_id)
        r.duration_ms, r.error = duration_ms, error
        if self.keep_evidence and state and state.get("book") is not None:
            r.evidence = {
                e.id: {
                    "tipo": e.kind,
                    "texto": e.body,
                    "nivel": e.level.value,
                    "pii": e.contains_pii,
                    "documento": e.document,
                    "seccion": e.section,
                    "fragment_id": str(e.fragment_id) if e.fragment_id else None,
                    "herramienta": e.tool,
                }
                for e in state["book"].all()
            }

    def pop(self, run_id: str) -> RunRecord | None:
        return self.runs.pop(run_id, None)


class LangfuseObserver(AgentObserver):
    """Una traza de Langfuse por análisis: span raíz, un span por nodo, una `generation` por
    llamada al modelo (modelo, tokens, destino, nivel) y eventos de dominio.

    El id de la traza es el `trace_id` del análisis (32 hex), el mismo de `audit_log`,
    `section_version` y `analysis_run`: desde un borrador se llega a su traza y al revés, y el
    eval puede colgar sus scores en ella.

    Sin `input` ni `output` en ningún objeto. El `detail` de los eventos solo se manda para los
    códigos de `_SAFE_DETAIL` (ids de documento, códigos de causa); el resto va sin detalle.
    """

    _SAFE_DETAIL = frozenset(
        {"escala_al_modelo_grande", "violaciones", "llm_error", "estado_insuficiente"}
    )

    def __init__(self, client: Any) -> None:
        self._lf = client
        self._roots: dict[str, Any] = {}
        self._spans: dict[tuple[str, str], Any] = {}

    @classmethod
    def from_env(cls) -> LangfuseObserver:
        return cls(langfuse_client())

    def run_started(self, run_id, *, ncr_id, disciplines):
        self._roots[run_id] = self._lf.start_observation(
            trace_context={"trace_id": run_id},
            name="analisis_8d",
            as_type="agent",
            metadata={"ncr_id": str(ncr_id), "disciplinas": ",".join(disciplines)},
        )

    def stage_started(self, run_id, stage):
        root = self._roots.get(run_id)
        if root is not None:
            self._spans[(run_id, stage)] = root.start_observation(
                name=stage, as_type="chain"
            )

    def stage_finished(self, run_id, stage, duration_ms, ok):
        span = self._spans.pop((run_id, stage), None)
        if span is not None:
            if not ok:
                span.update(level="ERROR", status_message="el nodo terminó con error")
            span.end()

    def event(self, run_id, stage, event, detail):
        root = self._roots.get(run_id)
        if root is not None:
            meta = {"etapa": stage}
            if event in self._SAFE_DETAIL:
                meta["detalle"] = detail[:200]
            root.create_event(name=event, metadata=meta)

    def tool_call(self, run_id, tool, duration_ms, ok):
        root = self._roots.get(run_id)
        if root is None:
            return
        span = root.start_observation(
            name=f"tool:{tool}",
            as_type="tool",
            metadata={"duracion_ms": duration_ms},
            level=None if ok else "ERROR",
        )
        span.end()

    def llm_call(self, run_id, call):
        root = self._roots.get(run_id)
        if root is None:
            return
        # `usage_details` solo con input/output: Langfuse suma todas las claves para el total, y
        # `output_tokens` ya incluye el razonamiento. El razonamiento va en metadata.
        # `cost_details` es el costo que reportó el proveedor: los modelos de este proyecto no
        # están en la tabla de precios de Langfuse, así que sin esto el costo sale vacío.
        extra: dict[str, Any] = {}
        if call.cost_usd is not None:
            extra["cost_details"] = {"total": call.cost_usd}
        gen = root.start_observation(
            name=f"llm:{call.stage}",
            as_type="generation",
            model=call.model,
            usage_details={"input": call.input_tokens, "output": call.output_tokens},
            metadata={
                "destino": call.destination,
                "nivel": call.level,
                "tier": call.tier,
                "intentos": call.attempts,
                "latencia_ms": call.latency_ms,
                "razonamiento_tokens": call.reasoning_tokens,
                "salida_visible_tokens": max(call.output_tokens - call.reasoning_tokens, 0),
                "finish_reason": call.finish_reason,
            },
            level=None if call.ok else "ERROR",
            **extra,
        )
        gen.end()

    def retrieved(self, run_id, search, refs):
        root = self._roots.get(run_id)
        if root is not None:
            root.create_event(
                name=f"recuperacion:{search}",
                metadata={"documentos": [f"{r.source_key}#{r.section}" for r in refs]},
            )

    def run_finished(self, run_id, *, state, duration_ms, error):
        root = self._roots.pop(run_id, None)
        for key in [k for k in self._spans if k[0] == run_id]:
            self._spans.pop(key).end()
        if root is not None:
            root.update(
                metadata={"duracion_ms": duration_ms, "error": error},
                level="ERROR" if error else None,
            )
            root.end()

    def close(self):
        self._lf.flush()


def langfuse_client() -> Any:
    """Cliente de Langfuse con host explícito.

    Sin LANGFUSE_HOST (o LANGFUSE_BASE_URL) el SDK manda a cloud.langfuse.com por defecto: eso
    sacaría metadatos de la planta a un servicio externo sin que nadie lo decidiera. Aquí falla.
    """
    host = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")
    if not host:
        raise RuntimeError(
            "TRACE_EXPORTER=langfuse sin LANGFUSE_HOST: se niega a usar el host por defecto "
            "(cloud.langfuse.com). Define LANGFUSE_HOST con tu instancia."
        )
    from langfuse import Langfuse  # dependencia opcional (grupo `observabilidad`)

    # Sin `mask`: en el SDK la máscara se aplica también a `metadata` y borraría lo único
    # que se manda. La garantía es estructural: este módulo nunca pasa input ni output.
    return Langfuse(base_url=host, environment=os.environ.get("ENTORNO", "dev"))


def observer_from_env() -> AgentObserver | None:
    """`TRACE_EXPORTER=langfuse` activa Langfuse; cualquier otro valor, ninguno."""
    if os.environ.get("TRACE_EXPORTER", "").lower() != "langfuse":
        return None
    return LangfuseObserver.from_env()
