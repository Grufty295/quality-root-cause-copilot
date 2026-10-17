"""SQL de la recuperación y del índice. Único módulo que toca `document` y `fragment`.

Mismo estilo que modules/auth/repository.py: funciones que reciben una conexión
y no hacen commit.

La búsqueda solo lee de `visible_fragments(usuario)` (0001, sección 9): el
filtro de permisos ocurre antes del ranking, así que un fragmento fuera de
alcance nunca compite por el top-k ni aparece en una traza.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.confidentiality import ConfidentialityLevel
from app.retrieval.codes import codes_tsquery, strip_codes
from app.retrieval.embedder import to_pgvector
from app.retrieval.models import DocumentKind, FragmentDraft, SearchHit, SearchMode

RRF_K = 60
"""Constante de Reciprocal Rank Fusion. 60 es el valor del artículo original;
con k alto, aparecer en ambas ramas pesa más que estar primero en una."""

CANDIDATE_POOL = 50
"""Candidatos por rama antes de fusionar."""

# Texto completo: la parte en español se arma con OR entre términos.
# plainto_tsquery une con AND; con una descripción de NCR de 30 palabras, AND
# exige que un fragmento las contenga todas y casi nada coincide.
# Los códigos van aparte, normalizados y por prefijo (ver codes.py).
_HYBRID_SQL = text(
    """
WITH vis AS MATERIALIZED (
    SELECT f.id, f.tsv, f.embedding, f.embedding_model
    FROM visible_fragments(CAST(:user_id AS uuid)) f
    JOIN document d ON d.id = f.document_id
    WHERE (CAST(:as_of AS date) IS NULL OR f.doc_date IS NULL OR f.doc_date <= CAST(:as_of AS date))
      AND (CAST(:kinds AS document_kind[]) IS NULL OR d.kind = ANY (CAST(:kinds AS document_kind[])))
      AND d.source_key <> ALL (CAST(:exclude AS text[]))
),
q AS (
    SELECT
        coalesce(
            nullif(replace(plainto_tsquery('spanish', :text_query)::text, '&', '|'), ''),
            ''
        )::tsquery
        || coalesce(to_tsquery('simple', CAST(:codes_query AS text)), ''::tsquery) AS tsq
),
lex AS (
    SELECT v.id, row_number() OVER (ORDER BY ts_rank_cd(v.tsv, q.tsq) DESC, v.id) AS r
    FROM vis v, q
    WHERE :use_lex AND v.tsv @@ q.tsq
    ORDER BY r
    LIMIT :pool
),
sem AS (
    SELECT v.id, row_number() OVER (ORDER BY v.embedding <=> CAST(:qvec AS vector), v.id) AS r
    FROM vis v
    WHERE :use_sem AND v.embedding_model = :model
    ORDER BY r
    LIMIT :pool
),
fused AS (
    SELECT id,
           sum(CASE WHEN src = 'sem' THEN :sem_w ELSE :lex_w END / (:rrf_k + r)) AS score,
           min(r) FILTER (WHERE src = 'lex') AS lex_rank,
           min(r) FILTER (WHERE src = 'sem') AS sem_rank
    FROM (SELECT id, r, 'lex' AS src FROM lex
          UNION ALL
          SELECT id, r, 'sem' AS src FROM sem) u
    GROUP BY id
),
ranked AS (
    SELECT f.id AS fragment_id, f.document_id, d.source_key, d.kind, d.title,
           f.section, f.ordinal, f.content, f.level, f.contains_pii, f.doc_date,
           f.plant_id, f.line_id,
           fu.score, fu.lex_rank, fu.sem_rank,
           row_number() OVER (PARTITION BY f.document_id ORDER BY fu.score DESC, f.id) AS doc_rank
    FROM fused fu
    JOIN fragment f ON f.id = fu.id
    JOIN document d ON d.id = f.document_id
)
SELECT fragment_id, document_id, source_key, kind, title, section, ordinal, content, level,
       contains_pii, doc_date, plant_id, line_id, score, lex_rank, sem_rank
FROM ranked
WHERE CAST(:per_doc AS int) IS NULL OR doc_rank <= CAST(:per_doc AS int)
ORDER BY score DESC, fragment_id
LIMIT :top_k
"""
)


# Cómo se lee cada modo: (ramas, peso léxico, peso vectorial, fragmentos por documento).
_MODE_PARAMS: dict[str, tuple[bool, bool, float, float, int | None]] = {
    "hybrid": (True, True, 1.0, 1.0, None),
    "text": (True, False, 1.0, 1.0, None),
    "vector": (False, True, 1.0, 1.0, None),
    "hybrid_w": (True, True, 1.0, 2.0, None),
    "hybrid_doc": (True, True, 1.0, 1.0, 1),
    "hybrid_wdoc": (True, True, 1.0, 2.0, 1),
}


def hybrid_search(
    conn: Connection,
    *,
    user_id: UUID,
    text_query: str,
    query_vector: Sequence[float] | None,
    embedding_model: str,
    mode: SearchMode,
    top_k: int,
    as_of: date | None = None,
    kinds: Sequence[DocumentKind] | None = None,
    exclude_sources: Sequence[str] = (),
) -> list[SearchHit]:
    use_lex, use_sem, lex_w, sem_w, per_doc = _MODE_PARAMS[mode]
    if use_sem and query_vector is None:
        raise ValueError(f"el modo {mode!r} requiere el vector de la consulta")

    rows = conn.execute(
        _HYBRID_SQL,
        {
            "user_id": user_id,
            "as_of": as_of,
            "kinds": [k.value for k in kinds] if kinds else None,
            "exclude": list(exclude_sources),
            "text_query": strip_codes(text_query),
            "codes_query": codes_tsquery(text_query),
            "use_lex": use_lex,
            "use_sem": use_sem,
            "qvec": to_pgvector(query_vector) if query_vector is not None else None,
            "model": embedding_model,
            "pool": max(CANDIDATE_POOL, top_k),
            "rrf_k": RRF_K,
            "lex_w": lex_w,
            "sem_w": sem_w,
            "per_doc": per_doc,
            "top_k": top_k,
        },
    ).mappings()
    return [SearchHit.model_validate(dict(r)) for r in rows]


_SECTIONS_SQL = text(
    """
SELECT f.id AS fragment_id, f.document_id, d.source_key, d.kind, d.title,
       f.section, f.ordinal, f.content, f.level, f.contains_pii, f.doc_date,
       f.plant_id, f.line_id,
       0.0 AS score, NULL::int AS lex_rank, NULL::int AS sem_rank
FROM visible_fragments(CAST(:user_id AS uuid)) f
JOIN document d ON d.id = f.document_id
WHERE d.source_key = ANY (CAST(:keys AS text[]))
  AND f.section = ANY (CAST(:sections AS text[]))
  AND (CAST(:kinds AS document_kind[]) IS NULL OR d.kind = ANY (CAST(:kinds AS document_kind[])))
  AND (CAST(:as_of AS date) IS NULL OR f.doc_date IS NULL OR f.doc_date <= CAST(:as_of AS date))
  AND d.source_key <> ALL (CAST(:exclude AS text[]))
ORDER BY array_position(CAST(:keys AS text[]), d.source_key), f.ordinal
LIMIT :limit
"""
)


def fragments_by_section(
    conn: Connection,
    *,
    user_id: UUID,
    source_keys: Sequence[str],
    sections: Sequence[str],
    kinds: Sequence[DocumentKind] | None = None,
    as_of: date | None = None,
    exclude_sources: Sequence[str] = (),
    limit: int = 20,
) -> list[SearchHit]:
    """Secciones concretas de documentos concretos, con los mismos filtros que la búsqueda
    (permisos, corte, exclusiones). Sirve para seguir un enlace: NCR → su 8D → D4."""
    if not source_keys or not sections:
        return []
    rows = conn.execute(
        _SECTIONS_SQL,
        {
            "user_id": user_id,
            "keys": list(source_keys),
            "sections": list(sections),
            "kinds": [k.value for k in kinds] if kinds else None,
            "as_of": as_of,
            "exclude": list(exclude_sources),
            "limit": limit,
        },
    ).mappings()
    return [SearchHit.model_validate(dict(r)) for r in rows]


# --------------------------------------------------------------------------- índice


def embedding_column_dim(conn: Connection) -> int:
    """Dimensión declarada de fragment.embedding (vector(N) guarda N en atttypmod)."""
    return int(
        conn.execute(
            text("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'fragment'::regclass AND attname = 'embedding'")
        ).scalar_one()
    )


def plant_lines(conn: Connection, plant_id: str) -> set[str] | None:
    """Líneas de la planta, o None si la planta no existe."""
    if conn.execute(text("SELECT 1 FROM plant WHERE id = :p"), {"p": plant_id}).first() is None:
        return None
    return set(conn.execute(text("SELECT id FROM line WHERE plant_id = :p"), {"p": plant_id}).scalars())


def get_document_state(conn: Connection, source_key: str) -> dict[str, Any] | None:
    """id, hash de contenido, versión de chunker y modelos de embedding del índice actual."""
    row = (
        conn.execute(
            text(
                """
                SELECT d.id,
                       d.metadata ->> 'content_hash'    AS content_hash,
                       d.metadata ->> 'chunker_version' AS chunker_version,
                       array_remove(array_agg(DISTINCT f.embedding_model), NULL) AS models,
                       count(f.id) AS fragments
                FROM document d
                LEFT JOIN fragment f ON f.document_id = d.id
                WHERE d.source_key = :k
                GROUP BY d.id
                """
            ),
            {"k": source_key},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def upsert_document(
    conn: Connection,
    *,
    source_key: str,
    kind: DocumentKind,
    title: str,
    plant_id: str,
    line_id: str | None,
    level: ConfidentialityLevel,
    contains_pii: bool,
    doc_date: date,
    metadata: dict[str, Any],
) -> UUID:
    document_id: UUID = conn.execute(
        text(
            """
            INSERT INTO document (source_key, kind, title, plant_id, line_id, level,
                                  contains_pii, doc_date, metadata)
            VALUES (:source_key, CAST(:kind AS document_kind), :title, :plant_id, :line_id,
                    CAST(:level AS confidentiality_level), :contains_pii, :doc_date,
                    CAST(:metadata AS jsonb))
            ON CONFLICT (source_key) DO UPDATE SET
                kind = EXCLUDED.kind, title = EXCLUDED.title,
                plant_id = EXCLUDED.plant_id, line_id = EXCLUDED.line_id,
                level = EXCLUDED.level, contains_pii = EXCLUDED.contains_pii,
                doc_date = EXCLUDED.doc_date, metadata = EXCLUDED.metadata
            RETURNING id
            """
        ),
        {
            "source_key": source_key,
            "kind": kind.value,
            "title": title,
            "plant_id": plant_id,
            "line_id": line_id,
            "level": level.value,
            "contains_pii": contains_pii,
            "doc_date": doc_date,
            "metadata": json.dumps(metadata, ensure_ascii=False, default=str),
        },
    ).scalar_one()
    return document_id


def cited_fragment_count(conn: Connection, document_id: UUID) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM citation c JOIN fragment f ON f.id = c.fragment_id WHERE f.document_id = :d"),
            {"d": document_id},
        ).scalar_one()
    )


def delete_fragments(conn: Connection, document_id: UUID) -> None:
    conn.execute(text("DELETE FROM fragment WHERE document_id = :d"), {"d": document_id})


def insert_fragments(
    conn: Connection,
    *,
    document_id: UUID,
    fragments: Sequence[FragmentDraft],
    vectors: Sequence[Sequence[float]],
    embedding_model: str,
    level: ConfidentialityLevel,
    contains_pii: bool,
) -> None:
    """El trigger fragment_inherit copia planta, línea y fecha del documento y
    sube el nivel si el documento es más alto; aquí se manda el del documento."""
    if len(fragments) != len(vectors):
        raise ValueError("fragmentos y vectores no coinciden")
    if not fragments:
        return
    conn.execute(
        text(
            """
            INSERT INTO fragment (document_id, ordinal, section, content, codes, level,
                                  contains_pii, embedding, embedding_model)
            VALUES (:document_id, :ordinal, :section, :content, :codes,
                    CAST(:level AS confidentiality_level), :contains_pii,
                    CAST(:embedding AS vector), :embedding_model)
            """
        ),
        [
            {
                "document_id": document_id,
                "ordinal": f.ordinal,
                "section": f.section,
                "content": f.content,
                "codes": f.codes,
                "level": level.value,
                "contains_pii": contains_pii,
                "embedding": to_pgvector(v),
                "embedding_model": embedding_model,
            }
            for f, v in zip(fragments, vectors, strict=True)
        ],
    )
