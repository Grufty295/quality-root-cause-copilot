"""Enums compartidos de la capa LLM.

Los valores coinciden con los tipos de Postgres (`confidentiality_level`,
`llm_destination`, `eightd_discipline`) para que se escriban tal cual en la base.
"""

from __future__ import annotations

from enum import StrEnum

from app.confidentiality.levels import ConfidentialityLevel

__all__ = ["ConfidentialityLevel", "Destination", "ModelTier", "Stage"]


class Destination(StrEnum):
    LOCAL = "local"
    API = "api"


class Stage(StrEnum):
    """Etapa del flujo que origina la llamada. Decide el tamaño del modelo."""

    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    EVAL = "eval"
    """Juez de los evals semánticos (app/evalkit/semantic.py). Pasa por el mismo router: lo
    confidencial se juzga en local, y queda en audit_log como cualquier otra llamada."""


class ModelTier(StrEnum):
    SMALL = "small"
    LARGE = "large"
