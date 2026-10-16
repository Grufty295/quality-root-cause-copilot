"""Búsqueda con permisos. Lo usan las tools del agente y el módulo `search` (paso 6 de la demo).

El usuario entra como `CurrentUser`, que solo produce la autenticación (sesión
del servidor). Nunca como un id suelto: así ninguna tool puede pasar un
`user_id` que haya propuesto el LLM.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import Connection

from app.modules.auth.models import CurrentUser
from app.retrieval import repository as repo
from app.retrieval.chunker import CHUNKER_VERSION
from app.retrieval.embedder import Embedder
from app.retrieval.models import DocumentKind, SearchHit, SearchQuery


class RetrievalService:
    def __init__(self, conn: Connection, embedder: Embedder) -> None:
        self._conn = conn
        self._embedder = embedder

    @property
    def index_version(self) -> str:
        """Para `section_version.index_version`: reproduce con qué índice salió un borrador."""
        return f"{CHUNKER_VERSION}+{self._embedder.model_name}"

    def search(self, user: CurrentUser, query: SearchQuery) -> list[SearchHit]:
        vector = (
            self._embedder.embed_query(query.text) if query.mode != "text" else None
        )
        return repo.hybrid_search(
            self._conn,
            user_id=user.id,
            text_query=query.text,
            query_vector=vector,
            embedding_model=self._embedder.model_name,
            mode=query.mode,
            top_k=query.top_k,
            as_of=query.as_of,
            kinds=query.kinds,
            exclude_sources=query.exclude_sources,
        )

    def sections(
        self,
        user: CurrentUser,
        source_keys: Sequence[str],
        sections: Sequence[str],
        *,
        kinds: Sequence[DocumentKind] | None = None,
        as_of: date | None = None,
        exclude_sources: Sequence[str] = (),
        limit: int = 20,
    ) -> list[SearchHit]:
        """Secciones de documentos ya identificados (p. ej. el D4 de un 8D citado por una NCR)."""
        return repo.fragments_by_section(
            self._conn,
            user_id=user.id,
            source_keys=source_keys,
            sections=sections,
            kinds=kinds,
            as_of=as_of,
            exclude_sources=exclude_sources,
            limit=limit,
        )
