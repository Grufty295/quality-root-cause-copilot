"""Ingesta del corpus al índice.

Idempotente: cada documento guarda el hash de su archivo y la versión del
chunker. Si nada cambió (archivo, chunker y modelo de embeddings), no se toca
y sus fragmentos conservan sus IDs, que es lo que mantiene válidas las citas.

Un documento por transacción: si uno falla, los demás quedan indexados y el
fallo se reporta con su causa (es la versión mínima de la DLQ del PRD).

Si un documento cambió y alguno de sus fragmentos ya está citado en un 8D,
no se reindexa: borrar esos fragmentos rompería la evidencia de un borrador o
de una versión aprobada. Se reporta como fallo para que alguien decida.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.ingest.frontmatter import CorpusDocument, FrontMatterError, parse_document
from app.retrieval import repository as repo
from app.retrieval.chunker import CHUNKER_VERSION, DEFAULT_MAX_CHARS, chunk_markdown
from app.retrieval.embedder import Embedder

Outcome = Literal["created", "updated", "unchanged"]
ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


class IngestError(Exception):
    """Fallo de un documento. El mensaje va al reporte; nunca incluye el contenido."""


@dataclass
class IngestReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    fragments: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed


class IngestService:
    def __init__(
        self,
        connect: ConnectionFactory,
        embedder: Embedder,
        *,
        plant_id: str,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self._connect = connect
        self._embedder = embedder
        self._plant_id = plant_id
        self._max_chars = max_chars

    def check_environment(self) -> None:
        """Falla antes de procesar nada si la base no está lista para este corpus."""
        with self._connect() as conn:
            dim = repo.embedding_column_dim(conn)
            if dim != self._embedder.dim:
                raise IngestError(
                    f"fragment.embedding es vector({dim}) y EMBEDDING_DIM={self._embedder.dim}: "
                    "cambiar de modelo exige una migración y reindexar"
                )
            if repo.plant_lines(conn, self._plant_id) is None:
                raise IngestError(f"la planta {self._plant_id!r} no existe: carga los catálogos antes de la ingesta")

    def ingest_directory(self, root: Path) -> IngestReport:
        report = IngestReport()
        for path in _corpus_files(root):
            name = str(path.relative_to(root))
            try:
                doc = parse_document(path.read_text(encoding="utf-8"))
                if doc.level_was_defaulted:
                    report.warnings.append((name, "sin confidencialidad válida: se indexa como confidencial"))
                with self._connect() as conn:
                    outcome, n = self.ingest_document(conn, doc, content_hash=_hash(path))
            except (FrontMatterError, IngestError, UnicodeDecodeError) as exc:
                report.failed.append((name, str(exc)))
                continue
            except SQLAlchemyError as exc:
                # Un error de la base en un documento no detiene el resto. Solo la
                # primera línea: el texto completo puede traer parámetros del INSERT.
                report.failed.append(
                    (name, f"{type(exc).__name__}: {(str(getattr(exc, 'orig', None) or exc).splitlines() or [''])[0]}")
                )
                continue
            getattr(report, outcome).append(doc.source_key)
            report.fragments += n
        return report

    def ingest_document(self, conn: Connection, doc: CorpusDocument, *, content_hash: str) -> tuple[Outcome, int]:
        line_id = self._resolve_line(conn, doc)
        state = repo.get_document_state(conn, doc.source_key)
        if (
            state is not None
            and state["content_hash"] == content_hash
            and state["chunker_version"] == CHUNKER_VERSION
            and state["models"] == [self._embedder.model_name]
        ):
            return "unchanged", 0

        drafts = chunk_markdown(
            source_key=doc.source_key, title=doc.title, kind=doc.kind, body=doc.body, max_chars=self._max_chars
        )
        if not drafts:
            raise IngestError("el documento no produjo fragmentos")

        if state is not None:
            cited = repo.cited_fragment_count(conn, state["id"])
            if cited:
                raise IngestError(
                    f"cambió, pero {cited} cita(s) apuntan a sus fragmentos; reindexarlo rompería esa evidencia"
                )

        document_id = repo.upsert_document(
            conn,
            source_key=doc.source_key,
            kind=doc.kind,
            title=doc.title,
            plant_id=self._plant_id,
            line_id=line_id,
            level=doc.level,
            contains_pii=doc.contains_pii,
            doc_date=doc.doc_date,
            metadata={
                **doc.extra,
                "tipo": doc.tipo,
                "lineas": list(doc.lines),
                "clientes": list(doc.customers),
                "content_hash": content_hash,
                "chunker_version": CHUNKER_VERSION,
            },
        )
        if state is not None:
            repo.delete_fragments(conn, document_id)

        vectors = self._embedder.embed_documents([d.content for d in drafts])
        repo.insert_fragments(
            conn,
            document_id=document_id,
            fragments=drafts,
            vectors=vectors,
            embedding_model=self._embedder.model_name,
            level=doc.level,
            contains_pii=doc.contains_pii,
        )
        return ("created" if state is None else "updated"), len(drafts)

    def _resolve_line(self, conn: Connection, doc: CorpusDocument) -> str | None:
        """`lineas` del front matter -> document.line_id.

        Todas las líneas de la planta = documento de planta (NULL). Una sola = esa
        línea. Un subconjunto de varias no se puede representar con una sola
        columna: se rechaza en lugar de ampliar la visibilidad en silencio.
        """
        lines = repo.plant_lines(conn, self._plant_id) or set()
        unknown = set(doc.lines) - lines
        if unknown:
            raise IngestError(f"líneas que no existen en {self._plant_id}: {sorted(unknown)}")
        if set(doc.lines) == lines:
            return None
        if len(doc.lines) == 1:
            return doc.lines[0]
        raise IngestError(
            f"lineas={list(doc.lines)} es un subconjunto de varias líneas; el esquema admite una línea o toda la planta"
        )


def _corpus_files(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        raise IngestError(f"no existe el directorio del corpus: {root}")
    yield from sorted(p for p in root.rglob("*.md") if p.is_file())


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
