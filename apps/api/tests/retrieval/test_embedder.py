"""FastEmbedEmbedder sin descargar modelo: se inyecta un doble de TextEmbedding.

Lo que se prueba aquí es el contrato del código (prefijos, dimensión, valores
por defecto). Que e5-large se comporte bien en el corpus se mide con el eval
de Recall@5, con el modelo real.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest

from app.retrieval.embedder import (
    EmbeddingDimensionError,
    EmbeddingSettings,
    FastEmbedEmbedder,
    to_pgvector,
)


class FakeTextEmbedding:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.seen: list[str] = []

    def embed(self, texts: list[str], batch_size: int = 256) -> Iterator[np.ndarray]:
        self.seen.extend(texts)
        for _ in texts:
            yield np.ones(self.dim, dtype=np.float32)


def make(dim: int = 4, **settings: str) -> tuple[FastEmbedEmbedder, FakeTextEmbedding]:
    embedder = FastEmbedEmbedder(EmbeddingSettings(dim=dim, **settings))
    fake = FakeTextEmbedding(dim)
    embedder._model = fake  # evita cargar el modelo real
    return embedder, fake


def test_default_is_e5_large_with_1024_dims():
    fields = EmbeddingSettings.model_fields
    assert fields["model"].default == "intfloat/multilingual-e5-large"
    assert fields["dim"].default == 1024
    assert fields["passage_prefix"].default == "passage: "
    assert fields["query_prefix"].default == "query: "


def test_documents_get_passage_prefix():
    embedder, fake = make()
    vectors = embedder.embed_documents(["falso contacto", "AMEF"])
    assert fake.seen == ["passage: falso contacto", "passage: AMEF"]
    assert len(vectors) == 2 and len(vectors[0]) == 4


def test_query_gets_query_prefix():
    embedder, fake = make()
    embedder.embed_query("intermitencia")
    assert fake.seen == ["query: intermitencia"]


def test_prefixes_can_be_disabled_for_models_that_do_not_use_them():
    embedder, fake = make(passage_prefix="", query_prefix="")
    embedder.embed_query("texto")
    assert fake.seen == ["texto"]


def test_wrong_dimension_fails_loudly():
    embedder, _ = make(dim=4)
    embedder._model = FakeTextEmbedding(3)
    with pytest.raises(EmbeddingDimensionError, match="3 dimensiones"):
        embedder.embed_query("x")


def test_empty_batch_does_not_touch_the_model():
    embedder, fake = make()
    assert embedder.embed_documents([]) == []
    assert fake.seen == []


def test_pgvector_literal():
    assert to_pgvector([0.5, -1.0]) == "[0.5,-1]"
