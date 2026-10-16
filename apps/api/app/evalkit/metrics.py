"""Métricas de ranking. Puras: no tocan base ni red.

La unidad es el *ancla* (documento + sección), no el fragmento: si mañana el chunker parte
una sección en dos, los qrels siguen valiendo y la métrica no se mueve por eso.
Ganancias graduadas: 2 = esencial (sin esto el agente no puede acertar), 1 = útil.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping, Sequence


def dedupe(ranked: Sequence[Hashable]) -> list[Hashable]:
    """Conserva la primera aparición de cada ancla: dos fragmentos de la misma sección cuentan una vez."""
    seen: set[Hashable] = set()
    out: list[Hashable] = []
    for key in ranked:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def recall_at_k(
    ranked: Sequence[Hashable],
    grades: Mapping[Hashable, int],
    k: int,
    *,
    min_grade: int = 1,
) -> float | None:
    """Fracción de anclas relevantes (grado >= min_grade) dentro de los primeros k fragmentos.

    None si el caso no tiene ninguna ancla de ese grado: no hay nada que recuperar y un 0 o un 1
    falsearía el promedio.
    """
    relevant = {a for a, g in grades.items() if g >= min_grade}
    if not relevant:
        return None
    found = relevant & set(ranked[:k])
    return len(found) / len(relevant)


def hit_at_k(
    ranked: Sequence[Hashable],
    grades: Mapping[Hashable, int],
    k: int,
    *,
    min_grade: int = 2,
) -> float | None:
    """1 si aparece al menos una ancla esencial entre los primeros k fragmentos."""
    relevant = {a for a, g in grades.items() if g >= min_grade}
    if not relevant:
        return None
    return 1.0 if relevant & set(ranked[:k]) else 0.0


def reciprocal_rank(
    ranked: Sequence[Hashable], grades: Mapping[Hashable, int], *, min_grade: int = 2
) -> float | None:
    """1/posición del primer fragmento esencial (0 si no sale en la lista)."""
    relevant = {a for a, g in grades.items() if g >= min_grade}
    if not relevant:
        return None
    for pos, key in enumerate(ranked, start=1):
        if key in relevant:
            return 1.0 / pos
    return 0.0


def ndcg_at_k(
    ranked: Sequence[Hashable], grades: Mapping[Hashable, int], k: int
) -> float | None:
    """nDCG con ganancia 2^g - 1. Cada ancla suma una sola vez (la primera vez que sale)."""
    ideal_gains = sorted((2**g - 1 for g in grades.values() if g > 0), reverse=True)
    if not ideal_gains:
        return None
    seen: set[Hashable] = set()
    dcg = 0.0
    for pos, key in enumerate(ranked[:k], start=1):
        g = grades.get(key, 0)
        if g > 0 and key not in seen:
            seen.add(key)
            dcg += (2**g - 1) / math.log2(pos + 1)
    idcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(ideal_gains[:k]))
    return dcg / idcg if idcg else None


def precision_at_k(
    ranked: Sequence[Hashable], grades: Mapping[Hashable, int], k: int
) -> float | None:
    """Fracción de los k fragmentos que caen en un ancla relevante. Mide el ruido que recibe el prompt."""
    top = ranked[:k]
    if not top or not any(g > 0 for g in grades.values()):
        return None
    return sum(1 for key in top if grades.get(key, 0) > 0) / len(top)


def mean(values: Sequence[float | None]) -> float | None:
    """Promedio ignorando los None (casos donde la métrica no aplica)."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None
