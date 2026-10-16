"""Embedder determinista para pruebas: bolsa de palabras con hashing, sin modelo.

No mide calidad semántica (eso es el eval de Recall@5 con el modelo real); sirve
para que la rama vectorial funcione y sea reproducible.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence


class HashingEmbedder:
    def __init__(self, dim: int = 1024, model_name: str = "test-hashing-v1") -> None:
        self._dim = dim
        self._model_name = model_name
        self.calls = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for token in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            v[h % self._dim] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]
