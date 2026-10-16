"""SQL de la persistencia del agente: lectura de versiones previas y escritura de borradores.

Mismo estilo que los demás repositorios: reciben una conexión y no hacen commit.
La inmutabilidad de `section_version` y `citation` la imponen triggers en la base.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.agent.graph import Prior


def prior_sections(conn: Connection, ncr_id: UUID) -> dict[str, Prior]:
    """Última versión por disciplina; si fue un rechazo, también el borrador que se rechazó."""
    rows = conn.execute(
        text(
            "SELECT discipline::text, version_no, kind::text, content, feedback, feedback_reason "
            "FROM section_version "
            "WHERE ncr_id = :n ORDER BY discipline, version_no DESC"
        ),
        {"n": ncr_id},
    ).all()
    by_disc: dict[str, list[Any]] = {}
    for r in rows:
        by_disc.setdefault(r.discipline, []).append(r)
    out: dict[str, Prior] = {}
    for disc, versions in by_disc.items():
        latest = versions[0]
        rejected_draft = None
        if latest.kind == "rechazo":
            rejected_draft = next(
                (v.content for v in versions[1:] if v.content is not None), None
            )
        out[disc] = Prior(
            latest.kind,
            latest.content,
            latest.feedback,
            rejected_draft,
            latest.feedback_reason,
        )
    return out


def insert_agent_version(
    conn: Connection,
    *,
    ncr_id: UUID,
    discipline: str,
    version_no: int,
    content: dict[str, Any],
    model: str,
    prompt_version: str,
    index_version: str,
    trace_id: str,
) -> UUID:
    return conn.execute(
        text(
            "INSERT INTO section_version (ncr_id, discipline, version_no, kind, content, author_id, model, "
            "prompt_version, index_version, trace_id) "
            "VALUES (:n, CAST(:d AS eightd_discipline), :v, 'agente', CAST(:c AS jsonb), NULL, :m, :pv, :iv, :t) "
            "RETURNING id"
        ),
        {
            "n": ncr_id,
            "d": discipline,
            "v": version_no,
            "c": json.dumps(content, ensure_ascii=False),
            "m": model,
            "pv": prompt_version,
            "iv": index_version,
            "t": trace_id,
        },
    ).scalar_one()


def insert_citations(
    conn: Connection, version_id: UUID, rows: list[tuple[str, UUID]]
) -> None:
    for claim_ref, fragment_id in rows:
        conn.execute(
            text(
                "INSERT INTO citation (section_version_id, claim_ref, fragment_id) VALUES (:v, :c, :f) "
                "ON CONFLICT DO NOTHING"
            ),
            {"v": version_id, "c": claim_ref, "f": fragment_id},
        )
