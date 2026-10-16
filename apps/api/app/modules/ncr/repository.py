"""SQL de las no conformidades. Recibe una conexion y no hace commit."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.confidentiality import ConfidentialityLevel
from app.confidentiality.classifier import CatalogTerm, Classification
from app.modules.ncr.models import LatestVersion, Ncr, NcrDraft, SectionView

_NCR_COLUMNS = (
    "n.id, n.code, n.plant_id, n.line_id, n.shift, n.part_id AS part_number, n.customer_id, "
    "n.description, n.detected_level::text AS detected_level, n.contains_pii, "
    "n.classification_reasons, n.status::text AS status, "
    "n.opened_by, n.created_at"
)


def _ncr(row: Any) -> Ncr:
    data = dict(row._mapping)
    if data["classification_reasons"] is not None:
        data["classification_reasons"] = tuple(data["classification_reasons"])
    return Ncr(**data)


def line_exists(conn: Connection, plant_id: str, line_id: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM line WHERE plant_id = :p AND id = :l"),
            {"p": plant_id, "l": line_id},
        ).first()
        is not None
    )


def part_customer(conn: Connection, part_number: str) -> tuple[bool, str | None]:
    """(existe, cliente de la parte)."""
    row = conn.execute(
        text("SELECT customer_id FROM part WHERE id = :p"), {"p": part_number}
    ).one_or_none()
    return (row is not None, row[0] if row else None)


def customer_exists(conn: Connection, customer_id: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM customer WHERE id = :c"), {"c": customer_id}
        ).first()
        is not None
    )


def customer_is_confidential(conn: Connection, customer_id: str) -> bool | None:
    row = conn.execute(
        text("SELECT is_confidential FROM customer WHERE id = :c"), {"c": customer_id}
    ).one_or_none()
    return row[0] if row else None


def catalog_terms(conn: Connection) -> list[CatalogTerm]:
    """Clientes y partes del catalogo con su nivel, para el clasificador.

    El nivel de una parte es el de su cliente.
    """
    terms = [
        CatalogTerm(name, level_of(confidential), "cliente")
        for name, confidential in conn.execute(
            text("SELECT name, is_confidential FROM customer")
        ).all()
    ]
    terms.extend(
        CatalogTerm(part_number, level_of(confidential), "parte")
        for part_number, confidential in conn.execute(
            text(
                "SELECT p.part_number, c.is_confidential FROM part p JOIN customer c ON c.id = p.customer_id"
            )
        ).all()
    )
    return terms


def level_of(confidential: bool) -> ConfidentialityLevel:
    return (
        ConfidentialityLevel.CONFIDENCIAL
        if confidential
        else ConfidentialityLevel.INTERNO
    )


def next_code(conn: Connection, year: int) -> str:
    """NCR-AAAA-NNNN, siguiente al mayor existente de ese año.

    Toma el maximo de lo que hay, no un contador propio: las NCR historicas que
    se carguen despues no chocan. El candado serializa las altas concurrentes.
    """
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('ncr_code'))"))
    prefix = f"NCR-{year}-"
    top = conn.execute(
        text(
            "SELECT max(CAST(substring(code FROM '[0-9]+$') AS integer)) FROM ncr "
            "WHERE code ~ ('^' || :prefix || '[0-9]+$')"
        ),
        {"prefix": prefix},
    ).scalar_one()
    return f"{prefix}{(top or 0) + 1:04d}"


def insert(
    conn: Connection,
    *,
    code: str,
    draft: NcrDraft,
    opened_by: UUID,
    classification: Classification,
) -> UUID:
    return conn.execute(
        text(
            "INSERT INTO ncr (code, plant_id, line_id, shift, part_id, customer_id, description, opened_by, "
            "detected_level, contains_pii, classification_reasons) "
            "VALUES (:code, :plant, :line, :shift, :part, :cust, :descr, :by, "
            "CAST(:level AS confidentiality_level), :pii, :reasons) RETURNING id"
        ),
        {
            "code": code,
            "plant": draft.plant_id,
            "line": draft.line_id,
            "shift": draft.shift,
            "part": draft.part_number,
            "cust": draft.customer_id,
            "descr": draft.description,
            "by": opened_by,
            "level": classification.level.value,
            "pii": classification.contains_pii,
            "reasons": list(classification.reasons),
        },
    ).scalar_one()


def get(conn: Connection, ncr_id: UUID, user_id: UUID) -> Ncr | None:
    """Solo si el usuario tiene alcance sobre su planta y linea."""
    row = conn.execute(
        text(
            f"SELECT {_NCR_COLUMNS} FROM ncr n WHERE n.id = :id AND user_can_access(:u, n.plant_id, n.line_id)"
        ),
        {"id": ncr_id, "u": user_id},
    ).one_or_none()
    return _ncr(row) if row else None


def list_visible(conn: Connection, user_id: UUID, limit: int) -> list[Ncr]:
    rows = conn.execute(
        text(
            f"SELECT {_NCR_COLUMNS} FROM ncr n WHERE user_can_access(:u, n.plant_id, n.line_id) "
            "ORDER BY n.created_at DESC, n.id LIMIT :limit"
        ),
        {"u": user_id, "limit": limit},
    ).all()
    return [_ncr(r) for r in rows]


def latest_sections(conn: Connection, ncr_id: UUID) -> list[SectionView]:
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (s.discipline) s.discipline::text AS discipline, s.version_no, "
            "s.kind::text AS kind, s.content, s.feedback, u.username AS author, s.created_at "
            "FROM section_version s LEFT JOIN app_user u ON u.id = s.author_id "
            "WHERE s.ncr_id = :id ORDER BY s.discipline, s.version_no DESC"
        ),
        {"id": ncr_id},
    ).all()
    return [SectionView(**r._mapping) for r in rows]


# --- versiones de seccion (revision humana) ---------------------------------


def lock_ncr(conn: Connection, ncr_id: UUID) -> None:
    """Serializa las revisiones de una NCR: dos usuarios no calculan el mismo version_no."""
    conn.execute(text("SELECT 1 FROM ncr WHERE id = :id FOR UPDATE"), {"id": ncr_id})


def latest_version(
    conn: Connection, ncr_id: UUID, discipline: str
) -> LatestVersion | None:
    row = conn.execute(
        text(
            "SELECT version_no, kind::text AS kind, content FROM section_version "
            "WHERE ncr_id = :n AND discipline = CAST(:d AS eightd_discipline) "
            "ORDER BY version_no DESC LIMIT 1"
        ),
        {"n": ncr_id, "d": discipline},
    ).one_or_none()
    return LatestVersion(**row._mapping) if row else None


def version(
    conn: Connection, ncr_id: UUID, discipline: str, version_no: int
) -> LatestVersion | None:
    """Una version concreta de una seccion (la usa el replay por Idempotency-Key)."""
    row = conn.execute(
        text(
            "SELECT version_no, kind::text AS kind, content FROM section_version "
            "WHERE ncr_id = :n AND discipline = CAST(:d AS eightd_discipline) AND version_no = :v"
        ),
        {"n": ncr_id, "d": discipline, "v": version_no},
    ).one_or_none()
    return LatestVersion(**row._mapping) if row else None


def insert_version(
    conn: Connection,
    *,
    ncr_id: UUID,
    discipline: str,
    version_no: int,
    kind: str,
    content: dict[str, Any] | None,
    feedback: str | None,
    author_id: UUID,
    feedback_reason: str | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO section_version "
            "(ncr_id, discipline, version_no, kind, content, feedback, feedback_reason, author_id) "
            "VALUES (:n, CAST(:d AS eightd_discipline), :v, CAST(:k AS section_version_kind), "
            "CAST(:c AS jsonb), :f, :r, :a)"
        ),
        {
            "n": ncr_id,
            "d": discipline,
            "v": version_no,
            "k": kind,
            "c": json.dumps(content) if content is not None else None,
            "f": feedback,
            "r": feedback_reason,
            "a": author_id,
        },
    )


def latest_kinds(conn: Connection, ncr_id: UUID) -> list[str]:
    """Tipo de la ultima version de cada disciplina que ya tiene borrador."""
    return list(
        conn.execute(
            text(
                "SELECT DISTINCT ON (discipline) kind::text FROM section_version "
                "WHERE ncr_id = :n ORDER BY discipline, version_no DESC"
            ),
            {"n": ncr_id},
        ).scalars()
    )


def set_status(conn: Connection, ncr_id: UUID, status: str) -> None:
    conn.execute(
        text("UPDATE ncr SET status = CAST(:s AS ncr_status) WHERE id = :id"),
        {"s": status, "id": ncr_id},
    )


def latest_section(
    conn: Connection, ncr_id: UUID, discipline: str
) -> SectionView | None:
    return next(
        (s for s in latest_sections(conn, ncr_id) if s.discipline == discipline), None
    )
