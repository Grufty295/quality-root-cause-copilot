"""Grafo del agente (LangGraph): un agente con flujo por etapas.

    guard_input -> gather -> d2 -> d4_small -> (d4_large) -> fin

* `guard_input`: detección de injection en el texto de la NCR. Si salta, se detiene.
* `gather`: tools (datos y recuperación), clasificación de sus resultados y
  cuarentena de fragmentos con injection.
* `d2`, `d4_*`: una llamada al modelo por etapa a través del gateway, que decide el
  destino. D4 empieza con el modelo pequeño y escala al grande si alguna causa se
  descarta (PRD: "el guardrail de citas ya funciona como evaluador").

El grafo no escribe en la base de nada que no sea lectura: lo que produce vuelve en
el estado y lo persiste `AnalysisService`, en una transacción propia y después de
las llamadas al modelo (nunca se sostiene un candado de la NCR durante un LLM).

LangGraph aporta aquí el cableado y la trazabilidad por nodo; la lógica vive en
métodos normales que se prueban sin él.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import Engine

from app.agent import prompts
from app.agent.catalog import CauseCatalog
from app.agent.evidence import EvidenceBook
from app.agent.guardrails import Violation, detect_injection, verify_d2, verify_d4
from app.agent.llm import (
    CallMeta,
    ConfidentialityLevel,
    GatewayStructuredResult,
    LLMError,
    Message,
    ModelGateway,
    ModelTier,
    RouteContext,
    Stage,
)
from app.agent.observe import (
    AgentObserver,
    CompositeObserver,
    LLMCallEvent,
    NodeCallbacks,
    RetrievedRef,
)
from app.agent.schemas import D2Content, D2Draft, D4Content, D4Draft
from app.agent.tools import QualityTools, ToolBudget, ToolError
from app.confidentiality.classifier import RuleClassifier
from app.modules.auth.models import CurrentUser
from app.modules.ncr import repository as ncr_repo
from app.modules.ncr.models import Ncr
from app.retrieval.embedder import Embedder
from app.retrieval.models import DocumentKind, SearchHit
from app.retrieval.service import RetrievalService

QUERY_CHARS = 600


_EIGHT_D_REF = re.compile(r"\b8D-\d{4}-\d{3}\b")


def linked_8d(hits: Sequence[SearchHit], limit: int) -> list[str]:
    """8Ds a un salto del top de casos, en orden de aparición: el propio 8D si salió (por lo
    general su D2) o el que cita una NCR ("8D relacionado"). El enlace lo lee el código, no el LLM."""
    out: list[str] = []
    for h in hits:
        if h.kind is DocumentKind.EIGHT_D:
            refs = [h.source_key]
        elif h.kind is DocumentKind.NCR:
            refs = _EIGHT_D_REF.findall(h.content)
        else:
            refs = []
        for ref in refs:
            if ref not in out:
                out.append(ref)
            if len(out) >= limit:
                return out
    return out


def build_query(description: str, part_number: str | None) -> str:
    """Consulta de las dos búsquedas de recuperación. El eval de recuperación usa esta misma
    función: si cambia aquí, cambia lo que se mide."""
    return " ".join(f"{description} {part_number or ''}".split())[:QUERY_CHARS]


D2_GROUPS = frozenset({"estacion", "turno"})


@dataclass(frozen=True)
class Prior:
    """Última versión de una disciplina, para regenerar con la retroalimentación."""

    kind: str
    content: dict | None
    feedback: str | None
    previous_draft: dict | None
    """Último contenido que el revisor rechazó (el de la versión anterior al rechazo)."""
    feedback_reason: str | None = None
    """Motivo tipificado del rechazo (causa_incorrecta, cita_irrelevante...), si el revisor lo dio."""


@dataclass(frozen=True)
class CallInfo:
    stage: str
    tier: str
    model: str
    destination: str
    level: str
    input_tokens: int
    output_tokens: int
    attempts: int


class AgentState(TypedDict, total=False):
    ncr: Ncr
    user: CurrentUser
    as_of: date | None
    exclude_sources: tuple[str, ...]
    disciplines: tuple[str, ...]
    prior: dict[str, Prior]
    catalog: CauseCatalog
    trace_id: str
    # trabajo
    book: EvidenceBook
    catalog_ids: list[tuple[str, Any]]
    index_version: str
    # resultados
    d2: D2Content | None
    d4: D4Content | None
    blocked: dict[str, str]
    events: list[dict[str, str]]
    calls: list[CallInfo]
    models: dict[str, str]
    d4_retry: str | None
    stop: bool
    observer: AgentObserver
    """Callbacks de la corrida (ver app/agent/observe.py). Lo pone `run`; los nodos no lo tocan."""


@dataclass
class AgentDeps:
    engine: Engine
    gateway: ModelGateway
    embedder: Embedder
    tool_budget: int = 14
    d4_max_rounds: int = 2
    expand_case_links: bool = False
    """Sigue los enlaces del top de `search_cases` (8D recuperado o NCR que cita un 8D) hasta
    la sección D4 de ese 8D. Apagado por defecto hasta que el eval del agente diga si ayuda:
    trae la causa del precedente, pero también la de 8D de otra causa (ver docs/evaluacion.md)."""
    max_linked_8d: int = 2
    observer: AgentObserver | None = None
    """Observador de todas las corridas (p. ej. Langfuse). `run` puede sumar otro por corrida."""
    extra: dict[str, Any] = field(default_factory=dict)


class AgentGraph:
    def __init__(self, deps: AgentDeps) -> None:
        self._d = deps
        self.compiled = self._build()

    # ------------------------------------------------------------------ cableado

    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("guard_input", self.guard_input)
        g.add_node("gather", self.gather)
        g.add_node("d2", self.d2)
        g.add_node("d4_small", self.d4_small)
        g.add_node("d4_large", self.d4_large)
        g.add_edge(START, "guard_input")
        g.add_conditional_edges(
            "guard_input", lambda s: END if s.get("stop") else "gather"
        )
        g.add_conditional_edges("gather", self._after_gather)
        g.add_conditional_edges(
            "d2", lambda s: "d4_small" if "D4" in s["disciplines"] else END
        )
        g.add_conditional_edges(
            "d4_small", lambda s: "d4_large" if s.get("d4_retry") else END
        )
        g.add_edge("d4_large", END)
        return g.compile()

    @staticmethod
    def _after_gather(s: AgentState) -> str:
        if "D2" in s["disciplines"]:
            return "d2"
        return "d4_small" if "D4" in s["disciplines"] else END

    async def run(
        self, state: AgentState, observer: AgentObserver | None = None
    ) -> AgentState:
        """Corre el grafo. `trace_id` es el id de la corrida (32 hex): lo comparten `audit_log`,
        `section_version`, `analysis_run` y la traza de Langfuse."""
        state.setdefault("blocked", {})
        state.setdefault("events", [])
        state.setdefault("calls", [])
        state.setdefault("models", {})
        run_id = state.setdefault("trace_id", uuid.uuid4().hex)
        obs = CompositeObserver([self._d.observer, observer])  # type: ignore[list-item]
        state["observer"] = obs
        obs.run_started(
            run_id, ncr_id=state["ncr"].id, disciplines=state["disciplines"]
        )
        started = time.perf_counter()
        final: AgentState | None = None
        error: str | None = None
        try:
            final = await self.compiled.ainvoke(  # type: ignore[assignment]
                state, config={"callbacks": [NodeCallbacks(obs, run_id)]}
            )
            return final  # type: ignore[return-value]
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            obs.run_finished(
                run_id,
                state=final,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

    # ------------------------------------------------------------------ nodos

    async def guard_input(self, state: AgentState) -> dict:
        hits = detect_injection(state["ncr"].description)
        if not hits:
            return {}
        reason = (
            "La descripción de la NCR contiene instrucciones dirigidas al agente "
            f"({', '.join(hits)}). No se generó ningún borrador; revisa el texto."
        )
        _event(state, "guard_input", "injection_en_ncr", ",".join(hits))
        return {"stop": True, "blocked": {d: reason for d in state["disciplines"]}}

    async def gather(self, state: AgentState) -> dict:
        return await asyncio.to_thread(self._gather_sync, state)

    def _gather_sync(self, state: AgentState) -> dict:
        ncr, user = state["ncr"], state["user"]
        book = EvidenceBook()
        with self._d.engine.connect() as conn:
            retrieval = RetrievalService(conn, self._d.embedder)
            tools = QualityTools(
                conn,
                user,
                retrieval,
                ToolBudget(self._d.tool_budget),
                as_of=state.get("as_of"),
                exclude_sources=state.get("exclude_sources", ()),
            )
            classifier = RuleClassifier(ncr_repo.catalog_terms(conn))
            end = min(ncr.created_at.date(), state["as_of"] or date.max)
            self._run_data_tools(state, tools, classifier, book, ncr, end)
            if "D4" in state["disciplines"]:
                self._run_retrieval(state, tools, book, ncr)
            catalog_ids = []
            if "D4" in state["disciplines"]:
                for entry in state["catalog"].entries():
                    ev = book.add_fragment(
                        fragment_id=entry.fragment_id,
                        document="Catálogo",
                        section=entry.code,
                        title="catálogo de causas",
                        content=entry.description,
                        level=entry.level,
                        contains_pii=entry.contains_pii,
                        catalog_code=entry.code,
                    )
                    catalog_ids.append((ev.id, entry))
            index_version = retrieval.index_version
        return {
            "book": book,
            "catalog_ids": catalog_ids,
            "index_version": index_version,
        }

    def _run_data_tools(
        self,
        state: AgentState,
        tools: QualityTools,
        classifier: RuleClassifier,
        book: EvidenceBook,
        ncr: Ncr,
        end: date,
    ) -> None:
        start = end - timedelta(days=30)
        calls = [
            lambda: tools.defect_summary(
                ncr.plant_id, ncr.line_id, start, end, group_by="estacion"
            ),
            lambda: tools.defect_summary(
                ncr.plant_id, ncr.line_id, start, end, group_by="turno"
            ),
        ]
        if "D4" in state["disciplines"]:
            calls += [
                lambda: tools.defect_summary(
                    ncr.plant_id, ncr.line_id, start, end, group_by="semana"
                ),
                lambda: tools.defect_summary(
                    ncr.plant_id, ncr.line_id, start, end, group_by="aplicador"
                ),
                lambda: tools.defect_summary(
                    ncr.plant_id, ncr.line_id, start, end, group_by="parte"
                ),
                lambda: tools.maintenance_history(
                    ncr.plant_id, ncr.line_id, end - timedelta(days=120), end
                ),
                lambda: tools.applicator_wear(ncr.plant_id, ncr.line_id, on=end),
                lambda: tools.crimp_summary(
                    ncr.plant_id, ncr.line_id, end - timedelta(days=60), end
                ),
                lambda: tools.change_log(
                    ncr.plant_id, ncr.line_id, end - timedelta(days=90), end
                ),
                lambda: tools.material_lots(ncr.plant_id, ncr.line_id, start, end),
            ]
        for call in calls:
            try:
                out = call()
            except ToolError as exc:
                _event(state, "gather", "tool_rechazada", str(exc)[:200])
                continue
            c = classifier.classify(out.text)
            book.add_tool(
                tool=out.tool,
                params=out.params,
                body=out.text,
                level=c.level,
                contains_pii=c.contains_pii,
            )

    def _run_retrieval(
        self, state: AgentState, tools: QualityTools, book: EvidenceBook, ncr: Ncr
    ) -> None:
        query = build_query(ncr.description, ncr.part_number)
        batches: list[list[SearchHit]] = []
        for name, search in (
            ("search_cases", tools.search_cases),
            ("search_controls", tools.search_controls),
        ):
            try:
                batches.append(search(query))
            except ToolError as exc:
                _event(state, "gather", "tool_rechazada", str(exc)[:200])
                batches.append([])
            _retrieved(state, name, batches[-1])
        if self._d.expand_case_links and batches[0]:
            linked = linked_8d(batches[0], self._d.max_linked_8d)
            if linked:
                try:
                    batches.append(tools.linked_case_causes(linked))
                    _event(state, "gather", "expansion_enlace", ",".join(linked))
                    _retrieved(state, "linked_case_causes", batches[-1])
                except ToolError as exc:
                    _event(state, "gather", "tool_rechazada", str(exc)[:200])
        seen: set[UUID] = set()
        for hits in batches:
            for h in hits:
                if h.fragment_id in seen:
                    continue
                seen.add(h.fragment_id)
                patterns = detect_injection(f"{h.title} {h.content}")
                if patterns:  # cuarentena: no entra al prompt
                    _event(
                        state,
                        "gather",
                        "fragmento_en_cuarentena",
                        f"{h.source_key}:{','.join(patterns)}",
                    )
                    continue
                book.add_fragment(
                    fragment_id=h.fragment_id,
                    document=h.source_key,
                    section=h.section,
                    title=h.title,
                    content=h.content,
                    level=h.level,
                    contains_pii=h.contains_pii,
                )

    async def d2(self, state: AgentState) -> dict:
        book = state["book"]
        prior = state["prior"].get("D2")
        # D2 describe el problema: solo los conteos de defectos. El mantenimiento y el
        # desgaste son evidencia causal de D4; verlos aquí invita a adelantar causas.
        # Solo los cortes que D2 pide; los de D4 (parte, aplicador, semana) traen más detalle y,
        # con él, partes de clientes confidenciales que mandarían un D2 interno a local.
        ids = {
            e.id
            for e in book.tools()
            if e.tool == "get_defect_summary"
            and (e.params or {}).get("agrupar_por") in D2_GROUPS
        }
        messages = prompts.d2_messages(
            state["ncr"],
            book.render(only=ids),
            previous=prior.previous_draft if prior else None,
            feedback=prior.feedback if prior else None,
            reason=prior.feedback_reason if prior else None,
        )
        ctx = self._ctx(state, Stage.D2, [e for e in book.all() if e.id in ids])
        content, why = await self._generate(
            state, Stage.D2, ctx, messages, D2Draft, lambda d: verify_d2(d, book), "D2"
        )
        if content is None:
            return {"blocked": {**state["blocked"], "D2": _explain(why)}}
        return {"d2": content}

    async def d4_small(self, state: AgentState) -> dict:
        return await self._d4(state, ModelTier.SMALL, None)

    async def d4_large(self, state: AgentState) -> dict:
        return await self._d4(state, ModelTier.LARGE, state.get("d4_retry"))

    async def _d4(
        self, state: AgentState, tier: ModelTier, violations_text: str | None
    ) -> dict:
        book, catalog = state["book"], state["catalog"]
        if not catalog.complete:
            reason = "No hay catálogo de causas visible (AMEF o SOP-QA-011); no se puede proponer D4."
            return {"blocked": {**state["blocked"], "D4": reason}, "d4_retry": None}
        prior = state["prior"].get("D4")
        d2 = state.get("d2")
        d2_dict = d2.model_dump() if d2 else _prior_d2(state)
        catalog_ids = state["catalog_ids"]
        listed = {i for i, _ in catalog_ids}
        messages = prompts.d4_messages(
            state["ncr"],
            book.render(only={e.id for e in book.all()} - listed),
            catalog_ids,
            d2=d2_dict,
            previous=prior.previous_draft if prior else None,
            feedback=prior.feedback if prior else None,
            reason=prior.feedback_reason if prior else None,
        )
        ctx = self._ctx(state, Stage.D4, book.all(), tier=tier)

        def verify(draft: D4Draft):
            content, violations, _ = verify_d4(draft, book, catalog)
            return content, violations

        # Una sola ronda por modelo: la cascada al grande es la segunda oportunidad.
        content, why = await self._generate(
            state,
            Stage.D4,
            ctx,
            messages,
            D4Draft,
            verify,
            "D4",
            note=violations_text,
            rounds=1,
        )
        if content is not None and content.estado_motivo:
            _event(
                state,
                "d4",
                "estado_insuficiente",
                content.causas_ocurrencia[0].codigo
                if content.causas_ocurrencia
                else "",
            )
        best = state.get("d4")
        if content is not None and (
            best is None
            or len(content.causas_ocurrencia) >= len(best.causas_ocurrencia)
        ):
            best = content
        out: dict[str, Any] = {"d4": best, "d4_retry": None}
        if why and tier is ModelTier.SMALL:
            out["d4_retry"] = _explain(why)
            _event(
                state,
                "d4",
                "escala_al_modelo_grande",
                ",".join(sorted({v.code for v in why})),
            )
        elif best is None:
            out["blocked"] = {
                **state["blocked"],
                "D4": _explain(why) or "El modelo no produjo un D4 válido.",
            }
        return out

    # ------------------------------------------------------------------ llamada al modelo

    async def _generate(
        self,
        state: AgentState,
        stage: Stage,
        ctx: RouteContext,
        messages: tuple,
        schema: type,
        verify,
        label: str,
        *,
        note: str | None = None,
        rounds: int = 2,
    ):
        """Llama al modelo y verifica; si hay violaciones, una corrección dentro del mismo modelo."""
        meta = CallMeta(
            user_id=state["user"].id,
            ncr_id=state["ncr"].id,
            trace_id=state["trace_id"],
            tags={
                "plant": state["ncr"].plant_id,
                "line": state["ncr"].line_id,
                "feature": "analisis_8d",
            },
        )
        convo = messages
        if note:
            convo = (*convo, prompts.retry_note(note))
        violations: list[Violation] = []
        content = None
        for attempt in range(rounds):
            try:
                res: GatewayStructuredResult[
                    Any
                ] = await self._d.gateway.complete_structured(meta, ctx, convo, schema)
            except LLMError as exc:
                _event(state, label, "llm_error", type(exc).__name__)
                _observer(state).llm_call(
                    state["trace_id"],
                    LLMCallEvent(
                        stage.value,
                        (ctx.tier.value if ctx.tier else ""),
                        "",
                        "",
                        ctx.level.value,
                        0,
                        0,
                        0,
                        ok=False,
                    ),
                )
                return None, [
                    Violation(
                        "llm",
                        f"No se pudo obtener una respuesta del modelo ({type(exc).__name__}).",
                    )
                ] + violations
            usage = res.output.usage
            state["calls"].append(
                CallInfo(
                    stage.value,
                    res.decision.tier.value,
                    res.decision.model,
                    res.decision.destination.value,
                    res.decision.level.value,
                    usage.input_tokens,
                    usage.output_tokens,
                    res.output.attempts,
                )
            )
            state["models"][label] = res.decision.model
            _observer(state).llm_call(
                state["trace_id"],
                LLMCallEvent(
                    stage.value,
                    res.decision.tier.value,
                    res.decision.model,
                    res.decision.destination.value,
                    res.decision.level.value,
                    usage.input_tokens,
                    usage.output_tokens,
                    res.output.attempts,
                ),
            )
            content, violations = verify(res.output.value)
            if not violations:
                return content, []
            _event(
                state,
                label,
                "violaciones",
                ",".join(sorted({v.code for v in violations})),
            )
            if attempt + 1 < rounds:
                convo = (
                    *convo,
                    Message(
                        role="assistant",
                        content=json.dumps(
                            res.output.value.model_dump(), ensure_ascii=False
                        ),
                    ),
                    prompts.correction(_explain(violations)),
                )
        return content, violations

    def _ctx(
        self,
        state: AgentState,
        stage: Stage,
        evidence,
        *,
        tier: ModelTier | None = None,
    ) -> RouteContext:
        ncr = state["ncr"]
        frags = [e for e in evidence if e.kind == "fragmento"]
        tools = [e for e in evidence if e.kind == "herramienta"]
        ncr_level = (
            None
            if ncr.detected_level is None
            else ConfidentialityLevel(ncr.detected_level)
        )
        input_level = (
            ConfidentialityLevel.highest([ncr_level, *(e.level for e in tools)])
            if ncr_level
            else None
        )
        return RouteContext(
            stage=stage,
            input_level=input_level,
            input_contains_pii=ncr.contains_pii is not False
            or any(e.contains_pii for e in tools),
            fragment_ids=tuple(e.fragment_id for e in frags if e.fragment_id),
            fragment_levels=tuple(e.level for e in frags),
            fragment_contains_pii=any(e.contains_pii for e in frags),
            tier=tier,
        )


# --------------------------------------------------------------------------- utilidades


def _observer(state: AgentState) -> AgentObserver:
    return state.get("observer") or AgentObserver()


def _event(state: AgentState, stage: str, event: str, detail: str) -> None:
    state.setdefault("events", []).append(
        {"stage": stage, "event": event, "detail": detail}
    )
    if "trace_id" in state:
        _observer(state).event(state["trace_id"], stage, event, detail)


def _retrieved(state: AgentState, search: str, hits: Sequence[SearchHit]) -> None:
    _observer(state).retrieved(
        state["trace_id"],
        search,
        [
            RetrievedRef(h.fragment_id, h.source_key, h.section, i)
            for i, h in enumerate(hits, start=1)
        ],
    )


def _explain(violations: list[Violation]) -> str:
    return "\n".join(
        f"- {v.detail}" + (f" ({v.where})" if v.where else "") for v in violations
    )


def _prior_d2(state: AgentState) -> dict | None:
    prior = state["prior"].get("D2")
    return prior.content if prior and prior.kind != "rechazo" else None
