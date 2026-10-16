"""Normalización de texto compartida por el clasificador y el inspector de fugas.

Los dos deben coincidir en qué es "el mismo texto": si el clasificador reconoce
`AX-4471-B` pero el inspector no (o al revés), un identificador pasa por uno y
se bloquea en el otro.
"""

from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Minúsculas y sin acentos; conserva espacios y puntuación."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def squash(text: str) -> str:
    """Minúsculas, sin acentos y solo alfanuméricos.

    Quitar separadores puede producir coincidencias entre palabras contiguas;
    para detectar fugas, un falso positivo es aceptable y un falso negativo no.
    """
    return "".join(ch for ch in fold(text) if ch.isalnum())


def fold_with_map(text: str) -> tuple[str, list[int]]:
    """`fold` por carácter, con el índice del carácter original de cada carácter resultante.

    Sirve para buscar sobre texto normalizado y volver a posiciones del texto
    original (reemplazar un hallazgo exige saber dónde está en el original).
    """
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        folded = fold(ch)
        out.append(folded)
        index.extend([i] * len(folded))
    return "".join(out), index


def squash_with_map(text: str) -> tuple[str, list[int]]:
    """Igual que `squash`, con el índice original de cada carácter conservado.

    Invariante (probada): `squash_with_map(t)[0] == squash(t)`. El redactor y el
    inspector de fugas deben coincidir en qué es "el mismo texto".
    """
    folded, index = fold_with_map(text)
    chars: list[str] = []
    kept: list[int] = []
    for ch, i in zip(folded, index, strict=True):
        if ch.isalnum():
            chars.append(ch)
            kept.append(i)
    return "".join(chars), kept
