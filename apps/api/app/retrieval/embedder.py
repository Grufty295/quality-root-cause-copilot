"""Embeddings locales.

Los documentos confidenciales no salen del equipo ni siquiera al indexarse
(PRD), así que el modelo corre en el proceso con fastembed (ONNX, CPU). La
ingesta y la búsqueda deben usar el mismo modelo: por eso cada fragmento guarda
`embedding_model` y la rama vectorial filtra por él.

Variables (ya están en .env.example):

    EMBEDDING_PROVIDER=fastembed
    EMBEDDING_MODEL=intfloat/multilingual-e5-large
    EMBEDDING_DIM=1024

Cambiar de modelo o de dimensión exige la migración correspondiente (0005 para
e5-large) y reindexar: fragment.embedding es vector(N) y la ingesta no mezcla
modelos.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Literal, Protocol

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore", frozen=True)

    provider: Literal["fastembed"] = "fastembed"
    """El .env.example menciona `ollama`; no está implementado. Si se configura,
    la validación falla al arrancar en lugar de indexar con otro modelo."""

    model: str = "intfloat/multilingual-e5-large"
    dim: int = Field(default=1024, gt=0)
    batch_size: int = Field(default=32, gt=0, le=512)
    passage_prefix: str = "passage: "
    query_prefix: str = "query: "
    """Los modelos e5 se entrenaron con estos prefijos; sin ellos la recuperación
    empeora. Se aplican aquí, en el código: no verificamos que fastembed los
    agregue por su cuenta para e5. Para un modelo sin prefijos, déjalos vacíos."""


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingDimensionError(RuntimeError):
    pass


class FastEmbedEmbedder:
    """Carga el modelo al primer uso (la descarga va a FASTEMBED_CACHE_PATH)."""

    def __init__(self, settings: EmbeddingSettings) -> None:
        self._settings = settings
        self._model: Any = None

    @property
    def model_name(self) -> str:
        return self._settings.model

    @property
    def dim(self) -> int:
        return self._settings.dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        prefixed = [f"{self._settings.passage_prefix}{t}" for t in texts]
        vectors = [v.tolist() for v in self._load().embed(prefixed, batch_size=self._settings.batch_size)]
        self._check(vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        prefixed = f"{self._settings.query_prefix}{text}"
        vector: list[float] = next(iter(self._load().embed([prefixed], batch_size=1))).tolist()
        self._check([vector])
        return vector

    def _load(self) -> Any:
        if self._model is None:
            # Import diferido: tarda y no hace falta en pruebas.
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._settings.model)
        return self._model

    def _check(self, vectors: list[list[float]]) -> None:
        if vectors and len(vectors[0]) != self._settings.dim:
            raise EmbeddingDimensionError(
                f"{self._settings.model} produce vectores de {len(vectors[0])} dimensiones; "
                f"EMBEDDING_DIM y la columna fragment.embedding esperan {self._settings.dim}"
            )


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Dependencia de FastAPI y de la ingesta. Un solo modelo cargado por proceso."""
    return FastEmbedEmbedder(EmbeddingSettings())


def to_pgvector(vector: Sequence[float]) -> str:
    """Literal de pgvector ('[0.1,0.2,...]') para usar con CAST(:v AS vector)."""
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"
