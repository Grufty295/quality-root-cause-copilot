"""Servicio de análisis: valida quién puede, corre el grafo y persiste los borradores.

Orden deliberado:

1. lectura (alcance, versiones previas, catálogo) en una transacción corta;
2. el grafo, que llama a los modelos, sin ninguna transacción ni candado abierto;
3. escritura en una transacción nueva, que primero comprueba que nadie tocó las
   secciones mientras el modelo trabajaba (si cambió, 409 y no se escribe nada).

Qué disciplinas se generan:

* sin borrador previo, o con la última versión rechazada (regenera con la
  retroalimentación): se genera;
* con un borrador sin revisar (del agente o editado): no se sobrescribe; hay que
  rechazarlo con retroalimentación, que es el camino del PRD;
* aprobada: es final.

Cada análisis es una corrida en `analysis_run` (id = trace_id): se abre antes del grafo, se
cierra con su estado, tiempos por etapa, costo (desde `audit_log`) y manifiesto. Con
`Idempotency-Key`, repetir la petición devuelve la corrida ya hecha sin llamar al modelo; sin
clave, una segunda petición mientras la primera trabaja recibe 409 en vez de duplicar gasto.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.agent import repository as repo
from app.agent import runs
from app.agent.catalog import load_catalog
from app.agent.graph import AgentDeps, AgentGraph, AgentState, CallInfo
from app.agent.guardrails import detect_injection
from app.agent.guardrails.diagnostics import as_events, diagnose
from app.agent.limits import AnalysisLimiter
from app.agent.manifest import build_manifest
from app.agent.observe import AgentObserver, CompositeObserver, RecordingObserver
from app.agent.prompts import PROMPT_VERSION, case_block
from app.core.errors import Conflict, Forbidden, Invalid
from app.modules.auth.models import CurrentUser
from app.modules.ncr import repository as ncr_repo
from app.modules.ncr.review import status_for
from app.modules.ncr.service import NcrService

ANALYZE_ROLES = ("ingeniero",)
DISCIPLINES = ("D2", "D4")


@dataclass
class AnalysisResult:
    trace_id: str
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    """disciplina -> {version_no, model, content}"""
    blocked: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, str]] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    status: str = "en_curso"
    replayed: bool = False
    """True si la respuesta es la de una corrida anterior con la misma Idempotency-Key."""
    duration_ms: int | None = None
    stage_ms: dict[str, int] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    """Llamadas, tokens y costo estimado/reportado de la corrida (de `audit_log`)."""
    config_id: str | None = None

    @property
    def run_id(self) -> str:
        return self.trace_id


class AnalysisService:
    def __init__(self, deps: AgentDeps, *, limiter: AnalysisLimiter | None = None) -> None:
        self._deps = deps
        self._graph = AgentGraph(deps)
        self._limiter = limiter or AnalysisLimiter.from_env()

    async def analyze(
        self,
        user: CurrentUser,
        ncr_id: UUID,
        *,
        disciplines: tuple[str, ...] | None = None,
        as_of: date | None = None,
        exclude_sources: tuple[str, ...] = (),
        idempotency_key: str | None = None,
        observer: AgentObserver | None = None,
        agent_instructions: str | None = None,
    ) -> AnalysisResult:
        if user.role not in ANALYZE_ROLES:
            raise Forbidden("Tu rol no ejecuta el agente")
        instructions = " ".join((agent_instructions or "").split()) or None
        if instructions:
            hits = detect_injection(instructions)
            if hits:
                # Se rechaza antes de crear la corrida: el ingeniero corrige el texto y reintenta.
                raise Invalid(
                    "Las indicaciones parecen órdenes para cambiar las reglas del agente "
                    f"({', '.join(hits)}). Descríbelas como qué revisar o qué considerar."
                )
        wanted = tuple(
            d for d in DISCIPLINES if disciplines is None or d in disciplines
        )
        if idempotency_key:
            previous = await asyncio.to_thread(
                self._replay, user, ncr_id, idempotency_key
            )
            if previous is not None:
                return previous

        # Cupo después del replay: repetir una Idempotency-Key ya resuelta no consume un análisis.
        with self._limiter.slot(user.id):
            return await self._run(
                user,
                ncr_id,
                wanted=wanted,
                as_of=as_of,
                exclude_sources=exclude_sources,
                idempotency_key=idempotency_key,
                observer=observer,
                instructions=instructions,
            )

    async def _run(
        self,
        user: CurrentUser,
        ncr_id: UUID,
        *,
        wanted: tuple[str, ...],
        as_of: date | None,
        exclude_sources: tuple[str, ...],
        idempotency_key: str | None,
        observer: AgentObserver | None,
        instructions: str | None,
    ) -> AnalysisResult:
        ncr, prior, catalog, versions, skipped, todo = await asyncio.to_thread(
            self._read, user, ncr_id, wanted, as_of
        )
        run_id = uuid.uuid4().hex
        await asyncio.to_thread(
            self._start_run, run_id, ncr_id, user.id, todo, idempotency_key
        )
        recorder = RecordingObserver()
        started = time.perf_counter()
        final: AgentState | None = None
        written: dict[str, dict[str, Any]] = {}
        error: str | None = None
        try:
            state: AgentState = {
                "ncr": ncr,
                "user": user,
                "as_of": as_of,
                "exclude_sources": exclude_sources,
                "disciplines": todo,
                "prior": prior,
                "catalog": catalog,
                "trace_id": run_id,
                "instructions": instructions,
            }
            if instructions:
                state["events"] = [
                    {
                        "stage": "entrada",
                        "event": "indicaciones_revisor",
                        "detail": f"{len(instructions)} caracteres",
                    }
                ]
            final = await self._graph.run(
                state,
                CompositeObserver([recorder, observer]),  # type: ignore[list-item]
            )
            final["events"] = [
                *final.get("events", []),
                *_diagnostic_events(ncr, final),
            ]
            produced = {"D2": final.get("d2"), "D4": final.get("d4")}
            if any(produced[d] is not None for d in todo):
                written = await asyncio.to_thread(
                    self._write, ncr_id, final, produced, versions
                )
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            closed = await asyncio.to_thread(
                self._finish_run,
                run_id,
                todo,
                final,
                written,
                skipped,
                error,
                int((time.perf_counter() - started) * 1000),
                recorder.pop(run_id),
                instructions,
            )
        result = AnalysisResult(
            trace_id=run_id,
            blocked=dict(final.get("blocked", {})),
            skipped=skipped,
            events=final.get("events", []),
            calls=final.get("calls", []),
            **closed,
        )
        result.sections.update(written)
        return result

    # ------------------------------------------------------------------ corridas

    def _replay(
        self, user: CurrentUser, ncr_id: UUID, key: str
    ) -> AnalysisResult | None:
        with self._deps.engine.connect() as conn:
            NcrService(conn).get(user, ncr_id)  # 404 si no tiene alcance
            run = runs.find_by_key(conn, ncr_id, key)
            if run is None:
                return None
            if run.status == "en_curso":
                raise Conflict(
                    "Esa petición todavía se está procesando; vuelve a consultar en un momento"
                )
            sections: dict[str, dict[str, Any]] = {}
            for d, info in (run.outcome.get("written") or {}).items():
                v = ncr_repo.version(conn, ncr_id, d, info["version_no"])
                if v is not None:
                    sections[d] = {
                        "version_no": info["version_no"],
                        "model": info.get("model"),
                        "content": v.content,
                    }
        return AnalysisResult(
            trace_id=run.id,
            sections=sections,
            blocked=run.outcome.get("blocked") or {},
            skipped=run.outcome.get("skipped") or {},
            events=[
                {"stage": e[0], "event": e[1], "detail": ""}
                for e in run.outcome.get("events") or []
            ],
            status=run.status,
            replayed=True,
            duration_ms=run.duration_ms,
            stage_ms=run.stage_ms,
            usage=run.outcome.get("usage") or {},
            config_id=run.manifest.get("config_id"),
        )

    def _start_run(
        self,
        run_id: str,
        ncr_id: UUID,
        user_id: UUID,
        todo: tuple[str, ...],
        key: str | None,
    ) -> None:
        with self._deps.engine.begin() as conn:
            runs.start(
                conn,
                run_id=run_id,
                ncr_id=ncr_id,
                user_id=user_id,
                disciplines=todo,
                idempotency_key=key,
            )

    def _finish_run(
        self,
        run_id: str,
        todo: tuple[str, ...],
        final: AgentState | None,
        written: dict[str, dict[str, Any]],
        skipped: dict[str, str],
        error: str | None,
        duration_ms: int,
        record,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        """Cierra la corrida. Nunca tapa el error original: si cerrar falla, se registra y sigue."""
        state = final or {}
        manifest = build_manifest(
            self._deps,
            index_version=state.get("index_version"),
            catalog=state.get("catalog"),
        )
        stage_ms = dict(record.stage_ms) if record else {}
        status = runs.status_for(todo, written, error)
        try:
            with self._deps.engine.begin() as conn:
                usage = runs.llm_usage(conn, run_id)
                outcome = {
                    "written": {
                        d: {"version_no": w["version_no"], "model": w["model"]}
                        for d, w in written.items()
                    },
                    "blocked": state.get("blocked") or {},
                    "skipped": skipped,
                    # Solo etapa y código: el detalle puede traer ids de documentos.
                    "events": [
                        [e.get("stage"), e.get("event")]
                        for e in state.get("events") or []
                    ],
                    "usage": usage,
                    "error": error,
                }
                if instructions:
                    # Texto completo: el auditor necesita ver qué se le pidió al agente. /runs ya
                    # excluye al inspector; el texto se clasificó en `_ctx` antes de cualquier envío.
                    outcome["agent_instructions"] = instructions
                runs.finish(
                    conn,
                    run_id,
                    status=status,
                    duration_ms=duration_ms,
                    stage_ms=stage_ms,
                    outcome=outcome,
                    manifest=manifest,
                )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "no se pudo cerrar analysis_run %s", run_id
            )
            usage = {}
        return {
            "status": status,
            "duration_ms": duration_ms,
            "stage_ms": stage_ms,
            "usage": usage,
            "config_id": manifest["config_id"],
        }

    # ------------------------------------------------------------------ lectura

    def _read(
        self,
        user: CurrentUser,
        ncr_id: UUID,
        wanted: tuple[str, ...],
        as_of: date | None,
    ):
        versions: dict[str, int] = {}
        with self._deps.engine.connect() as conn:
            ncr = NcrService(conn).get(user, ncr_id)  # 404 si no tiene alcance
            prior = repo.prior_sections(conn, ncr_id)
            catalog = load_catalog(conn, user.id, as_of)
            # Versión que se leyó; la escritura verifica que siga igual.
            for d in wanted:
                latest = ncr_repo.latest_version(conn, ncr_id, d)
                versions[d] = latest.version_no if latest else 0
        skipped: dict[str, str] = {}
        todo: list[str] = []
        for d in wanted:
            p = prior.get(d)
            if p is None or p.kind == "rechazo":
                todo.append(d)
            elif p.kind == "aprobacion":
                skipped[d] = "La sección ya está aprobada y es final."
            else:
                skipped[d] = (
                    "Ya hay un borrador sin revisar; recházalo con retroalimentación para que el agente regenere."
                )
        if not todo:
            raise Conflict(
                " ".join(f"{d}: {why}" for d, why in skipped.items())
                or "Nada que generar."
            )
        return ncr, prior, catalog, versions, skipped, tuple(todo)

    # ------------------------------------------------------------------ escritura

    def _write(
        self,
        ncr_id: UUID,
        final: AgentState,
        produced: dict,
        read_versions: dict[str, int],
    ):
        written: dict[str, dict[str, Any]] = {}
        book = final["book"]
        with self._deps.engine.begin() as conn:
            ncr_repo.lock_ncr(conn, ncr_id)
            for d, content in produced.items():
                if content is None:
                    continue
                latest = ncr_repo.latest_version(conn, ncr_id, d)
                current = latest.version_no if latest else 0
                if current != read_versions.get(d, 0):
                    raise Conflict(
                        f"{d} cambió mientras el agente trabajaba; vuelve a intentarlo"
                    )
                data = content.model_dump()
                version_id = repo.insert_agent_version(
                    conn,
                    ncr_id=ncr_id,
                    discipline=d,
                    version_no=current + 1,
                    content=data,
                    model=final["models"][d],
                    prompt_version=PROMPT_VERSION,
                    index_version=final["index_version"],
                    trace_id=final["trace_id"],
                )
                repo.insert_citations(conn, version_id, _citations(d, data, book))
                written[d] = {
                    "version_no": current + 1,
                    "model": final["models"][d],
                    "content": data,
                }
            ncr_repo.set_status(
                conn, ncr_id, status_for(ncr_repo.latest_kinds(conn, ncr_id))
            )
        return written


log = logging.getLogger(__name__)


def _dump(x: Any) -> Any:
    return x.model_dump() if hasattr(x, "model_dump") else x


def _diagnostic_events(ncr, final: AgentState) -> list[dict[str, str]]:
    """Diagnósticos de consistencia como eventos de la corrida. Solo informan: no cambian el
    borrador ni el estado. Un fallo aquí nunca debe tumbar el análisis."""
    try:
        d2, d4 = final.get("d2"), final.get("d4")
        if d2 is None and d4 is None:
            return []
        prior = (final.get("prior") or {}).get("D2")
        d2_content = (
            _dump(d2)
            if d2 is not None
            else (prior.content if prior and prior.kind != "rechazo" else None)
        )
        book = final.get("book")
        sources = [case_block(ncr), *(e.body for e in (book.all() if book else []))]
        found = diagnose(d2=d2_content, d4=_dump(d4), sources=sources)
        return as_events(found)
    except Exception:
        log.warning("diagnósticos de consistencia fallaron", exc_info=True)
        return []


def _citations(discipline: str, data: dict, book) -> list[tuple[str, UUID]]:
    """(claim_ref, fragment_id) por cada fragmento citado. Las tools y el reporte no son fragmentos."""
    rows: list[tuple[str, UUID]] = []

    def add(ref: str, sources: list[str]) -> None:
        for sid in sources:
            ev = book.get(sid)
            if ev is not None and ev.fragment_id is not None:
                rows.append((ref, ev.fragment_id))

    if discipline == "D2":
        for field_name in (
            "que",
            "por_que",
            "donde",
            "cuando",
            "quien",
            "como",
            "cuanto",
        ):
            add(field_name, data[field_name]["fuentes"])
    else:
        for i, causa in enumerate(data["causas_ocurrencia"]):
            for h in causa["evidencia"]:
                add(f"causas_ocurrencia[{i}]", h["fuentes"])
            for h in causa.get("evidencia_contradictoria") or []:
                add(f"causas_ocurrencia[{i}].contradictoria", h["fuentes"])
        nd = data.get("causa_no_deteccion")
        if nd:
            for h in nd["evidencia"]:
                add("causa_no_deteccion", h["fuentes"])
            for h in nd.get("evidencia_contradictoria") or []:
                add("causa_no_deteccion.contradictoria", h["fuentes"])
    return rows
