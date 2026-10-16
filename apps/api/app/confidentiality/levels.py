"""Niveles de confidencialidad.

Vive fuera de `agent/` porque lo usan la ingesta, la recuperación y el router:
ninguno de ellos debe depender del runtime del agente para conocer los niveles.
Los valores coinciden con el enum `confidentiality_level` de Postgres.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class ConfidentialityLevel(StrEnum):
    """Mismo orden que el enum de Postgres: publico < interno < confidencial."""

    PUBLICO = "publico"
    INTERNO = "interno"
    CONFIDENCIAL = "confidencial"

    @property
    def rank(self) -> int:
        return _LEVEL_RANK[self]

    @classmethod
    def highest(
        cls, levels: Iterable[ConfidentialityLevel | None]
    ) -> ConfidentialityLevel:
        """Nivel más alto de un contexto. `None` (sin clasificar) cuenta como confidencial.

        Un contexto vacío también se trata como confidencial: si nadie lo clasificó,
        no hay base para mandarlo fuera (fallo seguro).
        """
        result: ConfidentialityLevel | None = None
        for level in levels:
            if level is None:
                return cls.CONFIDENCIAL
            if result is None or level.rank > result.rank:
                result = level
        return result if result is not None else cls.CONFIDENCIAL


_LEVEL_RANK: dict[ConfidentialityLevel, int] = {
    ConfidentialityLevel.PUBLICO: 0,
    ConfidentialityLevel.INTERNO: 1,
    ConfidentialityLevel.CONFIDENCIAL: 2,
}
