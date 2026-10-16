"""Registro de corridas del agente (`analysis_run`): abrir, cerrar, buscar por clave.

Estados (ver 0014_analysis_run.sql):

    en_curso -> completada | parcial | sin_borrador | fallida
    en_curso -> abandonada          (la encuentra vieja otra corrida de la misma NCR)

Cada función recibe una conexión dentro de una transacción que abre quien llama: abrir y cerrar
son transacciones cortas, nunca abiertas durante la llamada al modelo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict

STALE_MINUTES = 15
"""Una corrida en curso más vieja que esto ya no está viva (el análisis tarda minutos, no
cuartos de hora): la siguiente de la misma NCR la marca `abandonada` y puede arrancar."""

FINAL_STATUSES = ("completada", "parcial", "sin_borrador", "fallida", "abandonada")


@dataclass(frozen=True)
class RunRow:
    id: str
    ncr_id: UUID
    requested_by: UUID
    idempotency_key: str | None
    disciplines: list[str]
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    stage_ms: dict[str, int]
    outcome: dict[str, Any]
    manifest: dict[str, Any]


_COLS = (
    "id, ncr_id, requested_by, idempotency_key, disciplines, status::text AS status, "
    "started_at, finished_at, duration_ms, stage_ms, outcome, manifest"
)


def find_by_key(conn: Connection, ncr_id: UUID, key: str) -> RunRow | None:
    row = (
        conn.execute(
            text(
                f"SELECT {_COLS} FROM analysis_run WHERE ncr_id = :n AND idempotency_key = :k"
            ),
            {"n": ncr_id, "k": key},
        )
        .mappings()
        .first()
    )
    return RunRow(**row) if row else None


def get(conn: Connection, run_id: str) -> RunRow | None:
    row = (
        conn.execute(
            text(f"SELECT {_COLS} FROM analysis_run WHERE id = :id"), {"id": run_id}
        )
        .mappings()
        .first()
    )
    return RunRow(**row) if row else None


def list_for_ncr(conn: Connection, ncr_id: UUID, limit: int = 50) -> list[RunRow]:
    rows = (
        conn.execute(
            text(
                f"SELECT {_COLS} FROM analysis_run WHERE ncr_id = :n "
                "ORDER BY started_at DESC LIMIT :l"
            ),
            {"n": ncr_id, "l": limit},
        )
        .mappings()
        .all()
    )
    return [RunRow(**r) for r in rows]


def start(
    conn: Connection,
    *,
    run_id: str,
    ncr_id: UUID,
    user_id: UUID,
    disciplines: tuple[str, ...],
    idempotency_key: str | None,
) -> None:
    """Abre la corrida. 409 si ya hay otra en curso para la NCR o si la clave ya se usó."""
    conn.execute(
        text(
            "UPDATE analysis_run SET status = 'abandonada', finished_at = now(), "
            "outcome = outcome || jsonb_build_object('motivo', 'sin cierre tras ' || :m || ' min') "
            "WHERE ncr_id = :n AND status = 'en_curso' "
            "AND started_at < now() - make_interval(mins => :m)"
        ),
        {"n": ncr_id, "m": STALE_MINUTES},
    )
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO analysis_run (id, ncr_id, requested_by, idempotency_key, disciplines) "
                    "VALUES (:id, :n, :u, :k, :d)"
                ),
                {
                    "id": run_id,
                    "n": ncr_id,
                    "u": user_id,
                    "k": idempotency_key,
                    "d": list(disciplines),
                },
            )
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "")
        if constraint == "analysis_run_idempotency":
            raise Conflict(
                "Esa Idempotency-Key ya se usó en otra corrida de esta NCR"
            ) from exc
        if constraint == "analysis_run_one_active":
            raise Conflict(
                "Ya hay un análisis en curso para esta NCR; espera a que termine"
            ) from exc
        raise


def finish(
    conn: Connection,
    run_id: str,
    *,
    status: str,
    duration_ms: int,
    stage_ms: dict[str, int],
    outcome: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if status not in FINAL_STATUSES:
        raise ValueError(f"estado final inválido: {status}")
    conn.execute(
        text(
            "UPDATE analysis_run SET status = CAST(:s AS analysis_run_status), finished_at = now(), "
            "duration_ms = :ms, stage_ms = CAST(:st AS jsonb), outcome = CAST(:o AS jsonb), "
            "manifest = CAST(:m AS jsonb) WHERE id = :id AND status = 'en_curso'"
        ),
        {
            "id": run_id,
            "s": status,
            "ms": duration_ms,
            "st": json.dumps(stage_ms),
            "o": json.dumps(outcome, ensure_ascii=False, default=str),
            "m": json.dumps(manifest, ensure_ascii=False, default=str),
        },
    )


def llm_usage(conn: Connection, run_id: str) -> dict[str, Any]:
    """Costo y tokens de la corrida, desde `audit_log` (la única fuente de verdad del gasto)."""
    row = (
        conn.execute(
            text(
                "SELECT count(*) AS llm_calls, "
                "coalesce(sum(tokens_in), 0) AS tokens_in, coalesce(sum(tokens_out), 0) AS tokens_out, "
                "coalesce(sum(cost_usd), 0) AS cost_est_usd, "
                "sum((tags->>'reported_cost_usd')::numeric) AS cost_reported_usd, "
                "coalesce(sum((tags->>'reasoning_tokens')::int), 0) AS reasoning_tokens, "
                "count(*) FILTER (WHERE coalesce(tags->>'outcome', 'ok') <> 'ok') AS llm_failures "
                "FROM audit_log WHERE trace_id = :t"
            ),
            {"t": run_id},
        )
        .mappings()
        .one()
    )
    return {
        "llm_calls": int(row["llm_calls"]),
        "tokens_in": int(row["tokens_in"]),
        "tokens_out": int(row["tokens_out"]),
        "reasoning_tokens": int(row["reasoning_tokens"]),
        "cost_est_usd": float(row["cost_est_usd"]),
        "cost_reported_usd": None
        if row["cost_reported_usd"] is None
        else float(row["cost_reported_usd"]),
        "llm_failures": int(row["llm_failures"]),
    }


def status_for(
    todo: tuple[str, ...], written: dict[str, Any], error: str | None
) -> str:
    if error:
        return "fallida"
    if written and all(d in written for d in todo):
        return "completada"
    return "parcial" if written else "sin_borrador"
