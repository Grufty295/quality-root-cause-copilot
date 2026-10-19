"""Capa HTTP del agente. Solo traduce HTTP al servicio."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agent import runs
from app.agent.graph import AgentDeps
from app.agent.service import ANALYZE_ROLES, AnalysisResult, AnalysisService
from app.core.db import get_conn, get_engine
from app.core.errors import AppError
from app.modules.auth.deps import current_user, require_role, require_role_released
from app.modules.auth.models import CurrentUser
from app.modules.ncr.service import NcrService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ncrs", tags=["agente"])

_lock = asyncio.Lock()


class AgentUnavailable(AppError):
    status_code = 503
    default_detail = "El agente no está disponible"


class AnalyzeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disciplines: list[Literal["D2", "D4"]] | None = None
    """Sin esto, todas las que se puedan generar."""
    agent_instructions: str | None = Field(default=None, max_length=1000)
    """Indicaciones opcionales del ingeniero para guiar al agente en esta corrida."""


class AnalyzeOut(BaseModel):
    trace_id: str
    run_id: str
    """Id de la corrida en `analysis_run`; es el mismo valor que `trace_id`."""
    status: str
    """completada, parcial, sin_borrador (la corrida terminó; ver `blocked`)."""
    replayed: bool = False
    """True: misma Idempotency-Key, se devuelve la corrida anterior sin llamar al modelo."""
    duration_ms: int | None = None
    stage_ms: dict[str, int] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    """llm_calls, tokens_in/out, reasoning_tokens, cost_est_usd, cost_reported_usd."""
    config_id: str | None = None
    """Hash del manifiesto (prompt, índice, catálogo, modelos, proveedor): misma config = comparable."""
    sections: dict[str, dict[str, Any]]
    blocked: dict[str, str]
    """Disciplina -> motivo por el que un guardrail impidió el borrador."""
    skipped: dict[str, str]
    events: list[dict[str, str]]
    calls: list[dict[str, Any]]
    """Una fila por llamada al modelo: etapa, tamaño, modelo, destino, nivel y tokens."""

    @classmethod
    def from_result(cls, r: AnalysisResult) -> AnalyzeOut:
        return cls(
            trace_id=r.trace_id,
            run_id=r.run_id,
            status=r.status,
            replayed=r.replayed,
            duration_ms=r.duration_ms,
            stage_ms=r.stage_ms,
            usage=r.usage,
            config_id=r.config_id,
            sections=r.sections,
            blocked=r.blocked,
            skipped=r.skipped,
            events=r.events,
            calls=[asdict(c) for c in r.calls],
        )


async def get_analysis_service(request: Request) -> AnalysisService:
    """Se construye en la primera petición: cargar el modelo de embeddings tarda."""
    service = getattr(request.app.state, "analysis", None)
    if service is not None:
        return service
    async with _lock:
        service = getattr(request.app.state, "analysis", None)
        if service is None:
            try:
                from app.agent.runtime import build_deps

                deps: AgentDeps = await asyncio.to_thread(build_deps, get_engine())
            except (
                Exception
            ) as exc:  # configuración inválida del LLM, base caída, modelo ausente
                # Sin esto el 503 no deja rastro en los logs y la causa real se pierde.
                log.exception("No se pudo construir el runtime del agente")
                # Para ModuleNotFoundError el nombre del módulo es lo que permite arreglarlo
                # (p. ej. `langfuse` si TRACE_EXPORTER=langfuse y la imagen no trae el grupo).
                missing = f": {exc.name}" if isinstance(exc, ModuleNotFoundError) and exc.name else ""
                raise AgentUnavailable(
                    f"El agente no está configurado ({type(exc).__name__}{missing})"
                ) from exc
            request.app.state.agent_deps = deps
            service = request.app.state.analysis = AnalysisService(deps)
    return service


@router.post("/{ncr_id}/analyze", response_model=AnalyzeOut)
async def analyze(
    ncr_id: UUID,
    body: AnalyzeIn | None = None,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=8, max_length=200
    ),
    # Sin `get_conn`: la conexion de autenticacion no debe seguir tomada durante minutos de analisis.
    user: CurrentUser = Depends(require_role_released(*ANALYZE_ROLES)),
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalyzeOut:
    disciplines = tuple(body.disciplines) if body and body.disciplines else None
    return AnalyzeOut.from_result(
        await service.analyze(
            user,
            ncr_id,
            disciplines=disciplines,
            idempotency_key=idempotency_key,
            agent_instructions=body.agent_instructions if body else None,
        )
    )


class RunOut(BaseModel):
    run_id: str
    status: str
    disciplines: list[str]
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    stage_ms: dict[str, int]
    usage: dict[str, Any]
    blocked: dict[str, str]
    written: dict[str, Any]
    events: list[list[str | None]]
    error: str | None
    config_id: str | None
    manifest: dict[str, Any]
    agent_instructions: str | None = None
    """Indicaciones que el ingeniero le dio al agente en esta corrida, si las hubo."""

    @classmethod
    def from_row(cls, r: runs.RunRow) -> RunOut:
        o = r.outcome
        return cls(
            run_id=r.id,
            status=r.status,
            disciplines=r.disciplines,
            started_at=r.started_at.isoformat(),
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
            duration_ms=r.duration_ms,
            stage_ms=r.stage_ms,
            usage=o.get("usage") or {},
            blocked=o.get("blocked") or {},
            written=o.get("written") or {},
            events=o.get("events") or [],
            error=o.get("error"),
            config_id=r.manifest.get("config_id"),
            manifest=r.manifest,
            agent_instructions=o.get("agent_instructions"),
        )


@router.get("/{ncr_id}/runs", response_model=list[RunOut])
def list_runs(
    ncr_id: UUID,
    user: CurrentUser = Depends(require_role("ingeniero", "gerente", "auditor")),
    conn=Depends(get_conn),
) -> list[RunOut]:
    """Corridas del agente sobre la NCR: estado, tiempos por etapa, costo y configuración.
    Lectura restringida a ingeniero, gerente y auditor (excluye al inspector de piso)."""
    NcrService(conn).get(user, ncr_id)  # 404 si no tiene alcance
    return [RunOut.from_row(r) for r in runs.list_for_ncr(conn, ncr_id)]


# ------------------------------------------------------------------ auditoría


class AuditEntryOut(BaseModel):
    """Una llamada al modelo tal como quedó en `audit_log`: solo metadatos, nunca contenido."""

    id: int
    created_at: str
    trace_id: str | None
    stage: str
    detected_level: str
    destination: str
    provider: str
    model: str
    tier: str | None
    simulated: bool
    fragments: int
    redaction_applied: bool
    pseudonymized: bool
    redactions: str | None
    """Tipos y conteos de lo redactado (p. ej. `cliente=2,persona=1`), sin valores."""
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    latency_ms: int | None
    outcome: str | None
    error: str | None
    finish_reason: str | None
    hash: str
    """Primeros 12 hex del hash encadenado de la fila."""


class ActivityOut(BaseModel):
    """Acción humana o de agente sobre la NCR: quién, qué y cuándo (de ncr, section_version y analysis_run)."""

    at: str
    kind: str
    """ncr_abierta, analisis_solicitado, borrador_agente, edicion, rechazo, aprobacion."""
    actor: str | None
    actor_role: str | None
    discipline: str | None = None
    version_no: int | None = None
    detail: str | None = None
    reason: str | None = None


class AuditOut(BaseModel):
    activity: list[ActivityOut] = []
    chain_ok: bool
    """La cadena de hashes de TODO el log está íntegra (audit_verify)."""
    chain_checked: int
    head_hash: str | None
    entries: list[AuditEntryOut]


_AUDIT_SQL = (
    "SELECT id, created_at, trace_id, stage, detected_level::text AS detected_level, "
    "destination::text AS destination, provider, model, cardinality(fragment_ids) AS fragments, "
    "redaction_applied, pseudonymized, tokens_in, tokens_out, cost_usd, latency_ms, tags, "
    "encode(hash, 'hex') AS hash FROM audit_log WHERE ncr_id = :n ORDER BY id DESC LIMIT 200"
)


_ACTIVITY_SQL = (
    "SELECT n.created_at AS at, 'ncr_abierta' AS kind, u.username AS actor, u.role::text AS role, "
    "NULL::text AS discipline, NULL::int AS version_no, NULL::text AS detail, NULL::text AS reason "
    "FROM ncr n JOIN app_user u ON u.id = n.opened_by WHERE n.id = :n "
    "UNION ALL "
    "SELECT r.started_at, 'analisis_solicitado', u.username, u.role::text, NULL, NULL, "
    "array_to_string(r.disciplines, ',') || ' · ' || r.status::text, NULL "
    "FROM analysis_run r JOIN app_user u ON u.id = r.requested_by WHERE r.ncr_id = :n "
    "UNION ALL "
    "SELECT s.created_at, CASE s.kind::text WHEN 'agente' THEN 'borrador_agente' ELSE s.kind::text END, "
    "u.username, u.role::text, s.discipline::text, s.version_no, s.feedback, s.feedback_reason "
    "FROM section_version s LEFT JOIN app_user u ON u.id = s.author_id WHERE s.ncr_id = :n "
    "ORDER BY 1 DESC"
)


@router.get("/{ncr_id}/audit", response_model=AuditOut)
def list_audit(
    ncr_id: UUID,
    user: CurrentUser = Depends(require_role("ingeniero", "gerente", "auditor")),
    conn=Depends(get_conn),
) -> AuditOut:
    """Llamadas al modelo sobre la NCR y estado de la cadena de auditoría.
    Lectura restringida a ingeniero, gerente y auditor (excluye al inspector de piso)."""
    from sqlalchemy import text

    NcrService(conn).get(user, ncr_id)  # 404 si no tiene alcance
    rows = conn.execute(text(_AUDIT_SQL), {"n": ncr_id}).mappings().all()
    verify = conn.execute(
        text("SELECT id, problem, head_hash FROM audit_verify()")
    ).all()
    broken = [v for v in verify if v.id is not None]
    tail = verify[-1] if verify else None
    checked = 0
    if (
        tail is not None
        and tail.problem
        and tail.problem.startswith("registros verificados:")
    ):
        checked = int(tail.problem.split(":", 1)[1])
    entries = []
    for r in rows:
        tags = r["tags"] or {}
        entries.append(
            AuditEntryOut(
                id=r["id"],
                created_at=r["created_at"].isoformat(),
                trace_id=r["trace_id"],
                stage=r["stage"],
                detected_level=r["detected_level"],
                destination=r["destination"],
                provider=r["provider"],
                model=r["model"],
                tier=tags.get("tier"),
                simulated=tags.get("simulated") == "true",
                fragments=r["fragments"] or 0,
                redaction_applied=r["redaction_applied"],
                pseudonymized=r["pseudonymized"],
                redactions=tags.get("redactions"),
                tokens_in=r["tokens_in"],
                tokens_out=r["tokens_out"],
                cost_usd=float(r["cost_usd"]) if r["cost_usd"] is not None else None,
                latency_ms=r["latency_ms"],
                outcome=tags.get("outcome"),
                error=tags.get("error"),
                finish_reason=tags.get("finish_reason"),
                hash=r["hash"][:12],
            )
        )
    activity = [
        ActivityOut(
            at=a["at"].isoformat(),
            kind=a["kind"],
            actor=a["actor"],
            actor_role=a["role"],
            discipline=a["discipline"],
            version_no=a["version_no"],
            detail=a["detail"],
            reason=a["reason"],
        )
        for a in conn.execute(text(_ACTIVITY_SQL), {"n": ncr_id}).mappings().all()
    ]
    return AuditOut(
        activity=activity,
        chain_ok=not broken,
        chain_checked=checked,
        head_hash=tail.head_hash if tail is not None else None,
        entries=entries,
    )