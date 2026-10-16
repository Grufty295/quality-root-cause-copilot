"""Capa HTTP del agente. Solo traduce HTTP al servicio."""

from __future__ import annotations

import asyncio
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
from app.modules.auth.deps import current_user, require_role
from app.modules.auth.models import CurrentUser
from app.modules.ncr.service import NcrService

router = APIRouter(prefix="/ncrs", tags=["agente"])

_lock = asyncio.Lock()


class AgentUnavailable(AppError):
    status_code = 503
    default_detail = "El agente no está disponible"


class AnalyzeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disciplines: list[Literal["D2", "D4"]] | None = None
    """Sin esto, todas las que se puedan generar."""


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
                raise AgentUnavailable(
                    f"El agente no está configurado ({type(exc).__name__})"
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
    user: CurrentUser = Depends(require_role(*ANALYZE_ROLES)),
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalyzeOut:
    disciplines = tuple(body.disciplines) if body and body.disciplines else None
    return AnalyzeOut.from_result(
        await service.analyze(
            user, ncr_id, disciplines=disciplines, idempotency_key=idempotency_key
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
        )


@router.get("/{ncr_id}/runs", response_model=list[RunOut])
def list_runs(
    ncr_id: UUID,
    user: CurrentUser = Depends(current_user),
    conn=Depends(get_conn),
) -> list[RunOut]:
    """Corridas del agente sobre la NCR: estado, tiempos por etapa, costo y configuración.
    Lectura para todo rol con alcance sobre la NCR (el auditor incluido)."""
    NcrService(conn).get(user, ncr_id)  # 404 si no tiene alcance
    return [RunOut.from_row(r) for r in runs.list_for_ncr(conn, ncr_id)]
